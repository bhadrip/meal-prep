"""Public food-share read path and deliberately limited HTML presentation."""

from __future__ import annotations

from html import escape
import re
from typing import Any

import httpx

from .config import Settings
from .infrastructure.repositories import DemoRepository


TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


async def read_shared_recipe(token: str, settings: Settings) -> dict[str, Any] | None:
    if not TOKEN_PATTERN.fullmatch(token):
        return None
    if not settings.supabase_configured:
        return DemoRepository.read_shared_recipe(token)
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/read_shared_recipe",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {settings.supabase_anon_key}",
                "Content-Type": "application/json",
            },
            json={"raw_token": token},
        )
    response.raise_for_status()
    share = response.json()
    return share or (DemoRepository.read_shared_recipe(token) if not settings.auth_required else None)


async def read_shared_food(token: str, settings: Settings) -> dict[str, Any] | None:
    if not TOKEN_PATTERN.fullmatch(token):
        return None
    if not settings.supabase_configured:
        return DemoRepository.read_shared_food(token)
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.post(
            f"{settings.supabase_url.rstrip('/')}/rest/v1/rpc/read_shared_food",
            headers={"apikey": settings.supabase_anon_key,
                     "Authorization": f"Bearer {settings.supabase_anon_key}",
                     "Content-Type": "application/json"},
            json={"raw_token": token},
        )
    response.raise_for_status()
    share = response.json()
    return share or (DemoRepository.read_shared_food(token) if not settings.auth_required else None)


def render_shared_meal_page(share: dict[str, Any]) -> str:
    meal = share["meal"]
    name = escape(str(meal.get("name") or "Shared meal"))
    notes = escape(str(meal.get("notes") or ""))
    parts = "".join(f"<li>{escape(str(part.get('name') or ''))}</li>"
                    for part in meal.get("components") or [])
    recipes = "".join(f"<article><h2>{escape(str(recipe.get('title') or 'Recipe'))}</h2>"
                      + "".join(f"<p>{escape(_instruction_text(step))}</p>" for step in recipe.get("instructions") or [])
                      + "</article>" for recipe in meal.get("recipes") or [])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>{name} · Meal Prep</title>
<style>:root{{font-family:ui-sans-serif,system-ui,sans-serif;color:#17211e;background:#f5f7f2}}body{{margin:0;padding:24px}}main{{max-width:760px;margin:32px auto;background:white;border:1px solid #dfe5de;border-radius:24px;padding:clamp(24px,5vw,48px)}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:clamp(2rem,5vw,3rem)}}p,li{{line-height:1.6}}</style><link rel="stylesheet" href="/static/mobile.css?v=1">
</head><body><main><p>Shared meal · Read only</p><h1>{name}</h1><p>{notes}</p><p>{escape(str(meal.get('servings') or ''))} servings</p><h2>Components</h2><ul>{parts}</ul>{recipes}</main></body></html>"""


def _ingredient_text(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value)
    amount = " ".join(str(value[key]) for key in ("quantity", "unit") if value.get(key))
    return " ".join(part for part in (amount, str(value.get("name") or "")) if part)


def _instruction_text(value: Any) -> str:
    return str(value.get("text") or value.get("instruction") or "") if isinstance(value, dict) else str(value)


def render_shared_recipe_page(share: dict[str, Any]) -> str:
    recipe = share["recipe"]
    title = escape(str(recipe.get("title") or "Shared recipe"))
    description = escape(str(recipe.get("description") or "A recipe shared from Meal Prep"))
    ingredients = "".join(f"<li>{escape(_ingredient_text(item))}</li>" for item in recipe.get("ingredients") or [])
    instructions = "".join(f"<li>{escape(_instruction_text(item))}</li>" for item in recipe.get("instructions") or [])
    minutes = recipe.get("totalMinutes")
    servings = recipe.get("servings")
    facts = " · ".join(part for part in (
        f"{escape(str(minutes))} min" if minutes is not None else "",
        f"{escape(str(servings))} servings" if servings is not None else "",
    ) if part)
    source_url = recipe.get("sourceUrl")
    source_link = ""
    if isinstance(source_url, str) and source_url.startswith(("https://", "http://")):
        source_link = f'<p><a href="{escape(source_url, quote=True)}" rel="noreferrer noopener" referrerpolicy="no-referrer">Original source ↗</a></p>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><meta property="og:type" content="article">
<meta property="og:title" content="{title} · Meal Prep"><meta property="og:description" content="{description}">
<title>{title} · Meal Prep</title>
<style>
:root{{font-family:ui-sans-serif,system-ui,sans-serif;color:#17211e;background:#f5f7f2}}
*{{box-sizing:border-box}}body{{margin:0;padding:24px}}main{{max-width:780px;margin:32px auto;background:white;border:1px solid #dfe5de;border-radius:24px;padding:clamp(24px,5vw,48px);box-shadow:0 18px 45px rgba(29,56,47,.1)}}
h1,h2{{font-family:Georgia,serif}}h1{{font-size:clamp(2rem,5vw,3.3rem);margin:.4em 0}}h2{{font-size:1.3rem;margin-top:2rem}}p,li{{line-height:1.6}}.eyebrow{{color:#467263;font-weight:700;letter-spacing:.08em;text-transform:uppercase;font-size:.75rem}}.description,.facts{{color:#64716c}}.columns{{display:grid;grid-template-columns:1fr 1.3fr;gap:32px}}a{{color:#173f35}}button{{background:#173f35;color:white;border:0;border-radius:12px;padding:13px 18px;font:inherit;font-weight:700;cursor:pointer}}#message{{min-height:24px;color:#467263}}@media(max-width:650px){{.columns{{grid-template-columns:1fr}}}}
</style><link rel="stylesheet" href="/static/mobile.css?v=1"></head><body><main>
<span class="eyebrow">Shared from Meal Prep</span><h1>{title}</h1><p class="description">{description}</p><p class="facts">{facts}</p>
<div class="columns"><section><h2>Ingredients</h2><ul>{ingredients}</ul></section><section><h2>Instructions</h2><ol>{instructions}</ol></section></div>
{source_link}
<button id="save-recipe" type="button">Save to my recipes</button><p id="message" role="status"></p>
</main><script src="/static/vendor/supabase.js" defer></script><script src="/static/share.js" defer></script></body></html>"""
