from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .models import InteractionEvent, ViewSpec
from .mcp_server import mcp, mcp_app
from .orchestrator import (
    confirm_swap_view,
    dashboard_view,
    easier_choices_view,
    onboarding_view,
    plan_review_view,
    retro_view,
    schedule_check_view,
    scoped_request_view,
    swap_options_view,
)
from .providers import ModelUnavailable, build_provider
from .state import STATE

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Meal Prep MVP",
    description="A governed meal-planning interface and MCP server backed by Supabase.",
    version="0.2.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def provider_or_none():
    try:
        return build_provider(get_settings())
    except ModelUnavailable:
        return None


def decided(view: ViewSpec, event: InteractionEvent, decision: str) -> ViewSpec:
    view.decision_id = STATE.record_decision(
        action=event.action,
        decision=decision,
        source=view.source,
        target_id=event.target_id,
        view_id=view.view_id,
    )
    return view


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/login", include_in_schema=False)
async def login() -> FileResponse:
    return FileResponse(STATIC_DIR / "login.html")


@app.get("/oauth/consent", include_in_schema=False)
async def oauth_consent() -> FileResponse:
    return FileResponse(STATIC_DIR / "oauth-consent.html")


@app.get("/api/auth/config")
async def auth_config() -> dict:
    settings = get_settings()
    return {
        "supabaseUrl": settings.supabase_url,
        "supabaseAnonKey": settings.supabase_anon_key,
        "authRequired": settings.auth_required,
        "redirectUrl": f"{settings.app_base_url.rstrip('/')}/login",
    }


@app.get("/api/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "provider": settings.model_provider,
        "model": settings.ollama_model if settings.model_provider == "ollama" else settings.openrouter_model,
        "model_enabled": settings.model_enabled,
        "persistence": "supabase" if settings.supabase_configured else "demo",
        "auth_required": settings.auth_required,
        "mcp_endpoint": "/mcp",
        "state_version": STATE.version,
    }


@app.get("/api/dashboard", response_model=ViewSpec)
async def dashboard() -> ViewSpec:
    provider = provider_or_none()
    return dashboard_view(STATE, model_label=provider.label if provider else None)


@app.get("/api/decisions")
async def decisions() -> dict:
    return {"items": STATE.decision_records[-25:]}


@app.post("/api/interactions", response_model=ViewSpec)
async def interact(event: InteractionEvent) -> ViewSpec:
    provider = provider_or_none()
    action = event.action

    if action == "home":
        return decided(dashboard_view(STATE, model_label=provider.label if provider else None), event, "fallback")
    if action == "review_onboarding":
        return decided(onboarding_view(STATE, editing=True), event, "review")
    if action == "complete_onboarding":
        try:
            STATE.complete_onboarding(event.parameters)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, "household size and planned dinners must be numbers") from exc
        return decided(
            dashboard_view(
                STATE,
                source="policy",
                model_label=provider.label if provider else None,
                toast="Your household setup is saved. Here is a practical starting plan.",
            ),
            event,
            "execute",
        )
    if action == "review_schedule":
        return decided(schedule_check_view(STATE), event, "review")
    if action == "save_schedule":
        try:
            STATE.save_week_schedule(event.parameters)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return decided(
            plan_review_view(STATE, toast="The week's rhythm is confirmed and reflected in this plan."),
            event,
            "execute",
        )
    if action == "start_retro":
        return decided(retro_view(STATE), event, "review")
    if action == "save_retro":
        try:
            STATE.save_retro(event.parameters)
        except (TypeError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        return decided(schedule_check_view(STATE), event, "execute")
    if action == "skip_retro":
        STATE.retro_due = False
        STATE.version += 1
        return decided(schedule_check_view(STATE), event, "skip")
    if action == "swap_meal":
        return decided(await swap_options_view(STATE, provider), event, "choose")
    if action == "make_easier":
        return decided(easier_choices_view(STATE), event, "clarify")
    if action == "choose_easier":
        goal = str(event.parameters.get("goal", "make dinner easier"))
        return decided(await swap_options_view(STATE, provider, goal=goal), event, "choose")
    if action == "select_swap":
        if not event.target_id:
            raise HTTPException(422, "target_id is required")
        try:
            return decided(confirm_swap_view(STATE, event.target_id), event, "confirm")
        except StopIteration as exc:
            raise HTTPException(404, "meal not found") from exc
    if action == "confirm_swap":
        if not event.target_id:
            raise HTTPException(422, "target_id is required")
        try:
            changed = STATE.swap(event.target_id, event.idempotency_key)
        except StopIteration as exc:
            raise HTTPException(404, "meal not found") from exc
        message = f"Tonight is now {STATE.meal()['name']}." if changed else "That change was already applied."
        return decided(
            dashboard_view(STATE, source="policy", model_label=provider.label if provider else None, toast=message),
            event,
            "execute" if changed else "idempotent_replay",
        )
    if action == "undo_swap":
        undone = STATE.undo_swap()
        return decided(
            dashboard_view(
                STATE,
                source="policy",
                model_label=provider.label if provider else None,
                toast="The last meal change was undone." if undone else "There is nothing to undo.",
            ),
            event,
            "execute" if undone else "no_op",
        )
    if action == "toggle_prep":
        if not event.target_id:
            raise HTTPException(422, "target_id is required")
        try:
            STATE.toggle_prep(event.target_id)
        except StopIteration as exc:
            raise HTTPException(404, "prep task not found") from exc
        return decided(dashboard_view(STATE, source="policy", model_label=provider.label if provider else None), event, "execute")
    if action == "scoped_request":
        text = str(event.parameters.get("text", "")).strip()
        if not text:
            raise HTTPException(422, "text is required")
        return decided(await scoped_request_view(STATE, provider, text[:600]), event, "ask")
    if action == "show_plan":
        if STATE.retro_due:
            view = retro_view(STATE)
        else:
            view = plan_review_view(STATE) if STATE.schedule_confirmed else schedule_check_view(STATE)
        return decided(view, event, "review")
    if action in {"start_cooking", "show_shopping"}:
        return decided(
            dashboard_view(STATE, source="policy", model_label=provider.label if provider else None, toast="That focused workflow is outside this small MVP."),
            event,
            "fallback",
        )

    raise HTTPException(400, f"Unsupported action: {action}")


# Mount last so the MCP ASGI app serves /mcp and OAuth metadata without
# shadowing the dashboard's ordinary HTTP routes.
app.mount("/", mcp_app)
