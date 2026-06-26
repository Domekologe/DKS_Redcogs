"""ActivityShop — earn virtual currency by activity and spend it in a shop.

Currency uses Red's built-in **bank**, so it integrates with the rest of Red.
Members earn for chatting (with a cooldown); they spend in a per-guild shop on
**roles** or plain **items** (kept in an inventory). Shop items are managed from
the web dashboard. Opt-in per guild, bilingual (DE/EN).
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import List, Optional

import discord
from discord import app_commands
from redbot.core import Config, bank, commands
from redbot.core.bot import Red

from .dks_dashboard import (
    Field,
    L,
    PanelSchema,
    SubmitResult,
    dashboard_list,
    dashboard_panel,
    register_dashboard,
    tr_lang,
    unregister_dashboard,
)

log = logging.getLogger("red.dks.activityshop")


class ActivityShop(commands.Cog):
    """Earn virtual currency by activity and spend it in a shop."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x5A09E5, force_registration=True)
        self.config.register_guild(
            enabled=False,
            language="en-US",
            earn=5,  # currency per message
            cooldown=60,
            items={},  # id -> {name, price, role, desc}
        )
        self.config.register_member(last_earn=0.0, inventory=[])

    async def cog_load(self) -> None:
        register_dashboard(self)

    def cog_unload(self) -> None:
        unregister_dashboard(self)

    @staticmethod
    def _t(lang: str, de: str, en: str) -> str:
        return de if str(lang).lower().startswith("de") else en

    async def _lang(self, guild) -> str:
        if guild is None:
            return "en-US"
        return await self.config.guild(guild).language()

    async def _cur(self, guild) -> str:
        try:
            return await bank.get_currency_name(guild)
        except Exception:
            return "credits"

    # ------------------------------------------------------------------ #
    # Earning
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild or not message.content:
            return
        if not isinstance(message.author, discord.Member):
            return
        conf = self.config.guild(message.guild)
        if not await conf.enabled():
            return
        earn = int(await conf.earn())
        if earn <= 0:
            return
        mconf = self.config.member(message.author)
        now = time.time()
        if now - await mconf.last_earn() < int(await conf.cooldown()):
            return
        await mconf.last_earn.set(now)
        try:
            await bank.deposit_credits(message.author, earn)
        except Exception:
            log.debug("deposit failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # Member commands
    # ------------------------------------------------------------------ #
    @commands.hybrid_command(name="coins", aliases=["wallet"])
    @commands.guild_only()
    @app_commands.describe(member="Whose balance to show (default: you)")
    async def coins(self, ctx: commands.Context, member: Optional[discord.Member] = None) -> None:
        """Show your currency balance."""
        member = member or ctx.author
        lang = await self._lang(ctx.guild)
        bal = await bank.get_balance(member)
        cur = await self._cur(ctx.guild)
        await ctx.send(self._t(lang, f"💰 {member.display_name}: **{bal}** {cur}", f"💰 {member.display_name}: **{bal}** {cur}"))

    @commands.hybrid_command(name="shop")
    @commands.guild_only()
    async def shop(self, ctx: commands.Context) -> None:
        """Show the shop."""
        lang = await self._lang(ctx.guild)
        if not await self.config.guild(ctx.guild).enabled():
            await ctx.send(self._t(lang, "Shop ist deaktiviert.", "Shop is disabled."))
            return
        items = await self.config.guild(ctx.guild).items()
        cur = await self._cur(ctx.guild)
        if not items:
            await ctx.send(self._t(lang, "Der Shop ist leer.", "The shop is empty."))
            return
        lines = []
        for it in items.values():
            role = ctx.guild.get_role(it.get("role")) if it.get("role") else None
            extra = f" → {role.mention}" if role else ""
            desc = f" — {it.get('desc')}" if it.get("desc") else ""
            lines.append(f"**{it.get('name')}** · {it.get('price')} {cur}{extra}{desc}")
        await ctx.send(embed=discord.Embed(title=self._t(lang, "🛒 Shop", "🛒 Shop"), description="\n".join(lines)[:4000], colour=await ctx.embed_colour()))

    @commands.hybrid_command(name="buy")
    @commands.guild_only()
    @app_commands.describe(item="Name of the item to buy")
    async def buy(self, ctx: commands.Context, *, item: str) -> None:
        """Buy an item from the shop."""
        lang = await self._lang(ctx.guild)
        if not await self.config.guild(ctx.guild).enabled():
            await ctx.send(self._t(lang, "Shop ist deaktiviert.", "Shop is disabled."))
            return
        items = await self.config.guild(ctx.guild).items()
        target = next((it for it in items.values() if str(it.get("name", "")).lower() == item.strip().lower()), None)
        if target is None:
            await ctx.send(self._t(lang, "Artikel nicht gefunden.", "Item not found."))
            return
        price = int(target.get("price", 0))
        if not await bank.can_spend(ctx.author, price):
            cur = await self._cur(ctx.guild)
            await ctx.send(self._t(lang, f"Zu wenig {cur}.", f"Not enough {cur}."))
            return
        role = ctx.guild.get_role(target.get("role")) if target.get("role") else None
        if role is not None:
            if role in ctx.author.roles:
                await ctx.send(self._t(lang, "Du hast diese Rolle bereits.", "You already have that role."))
                return
            if role >= ctx.guild.me.top_role:
                await ctx.send(self._t(lang, "Ich kann diese Rolle nicht vergeben (Hierarchie).", "I can't grant that role (hierarchy)."))
                return
        await bank.withdraw_credits(ctx.author, price)
        if role is not None:
            try:
                await ctx.author.add_roles(role, reason="Shop purchase")
            except discord.Forbidden:
                pass
        async with self.config.member(ctx.author).inventory() as inv:
            inv.append(target.get("name"))
        await ctx.send(self._t(lang, f"✅ Gekauft: **{target.get('name')}**", f"✅ Purchased: **{target.get('name')}**"))

    @commands.hybrid_command(name="inventory", aliases=["inv"])
    @commands.guild_only()
    async def inventory(self, ctx: commands.Context) -> None:
        """Show your inventory."""
        lang = await self._lang(ctx.guild)
        inv = await self.config.member(ctx.author).inventory()
        if not inv:
            await ctx.send(self._t(lang, "Dein Inventar ist leer.", "Your inventory is empty."))
            return
        counts: dict = {}
        for x in inv:
            counts[x] = counts.get(x, 0) + 1
        body = "\n".join(f"**{n}** ×{c}" for n, c in counts.items())
        await ctx.send(embed=discord.Embed(title=self._t(lang, "🎒 Inventar", "🎒 Inventory"), description=body, colour=await ctx.embed_colour()))

    # ------------------------------------------------------------------ #
    # Admin configuration
    # ------------------------------------------------------------------ #
    @commands.hybrid_group(name="shopset")
    @commands.admin_or_permissions(manage_guild=True)
    @commands.guild_only()
    async def shopset(self, ctx: commands.Context) -> None:
        """Configure the activity shop."""

    @shopset.command(name="enable")
    @app_commands.describe(on_off="Enable or disable the shop + earning")
    async def s_enable(self, ctx: commands.Context, on_off: bool) -> None:
        """Enable/disable the module for this server."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).enabled.set(on_off)
        state = self._t(lang, "aktiviert" if on_off else "deaktiviert", "enabled" if on_off else "disabled")
        await ctx.send(self._t(lang, f"Shop **{state}**.", f"Shop **{state}**."))

    @shopset.command(name="earn")
    @app_commands.describe(amount="Currency earned per message", cooldown="Seconds between earns")
    async def s_earn(self, ctx: commands.Context, amount: int, cooldown: int = 60) -> None:
        """Set the per-message earn amount + cooldown."""
        lang = await self._lang(ctx.guild)
        await self.config.guild(ctx.guild).earn.set(max(0, amount))
        await self.config.guild(ctx.guild).cooldown.set(max(0, cooldown))
        await ctx.send(self._t(lang, f"Verdienst: {max(0, amount)} / {max(0, cooldown)}s", f"Earn: {max(0, amount)} / {max(0, cooldown)}s"))

    @shopset.command(name="additem")
    @app_commands.describe(name="Item name", price="Price", role="Role to grant (optional)", description="Description (optional)")
    async def s_additem(self, ctx: commands.Context, name: str, price: int, role: Optional[discord.Role] = None, *, description: Optional[str] = None) -> None:
        """Add a shop item."""
        lang = await self._lang(ctx.guild)
        iid = uuid.uuid4().hex[:8]
        async with self.config.guild(ctx.guild).items() as items:
            items[iid] = {"name": name.strip(), "price": max(0, price), "role": role.id if role else None, "desc": (description or "").strip() or None}
        await ctx.send(self._t(lang, f"Artikel hinzugefügt: **{name}**", f"Item added: **{name}**"))

    @shopset.command(name="removeitem")
    @app_commands.describe(name="Item name to remove")
    async def s_removeitem(self, ctx: commands.Context, *, name: str) -> None:
        """Remove a shop item by name."""
        lang = await self._lang(ctx.guild)
        removed = False
        async with self.config.guild(ctx.guild).items() as items:
            for iid, it in list(items.items()):
                if str(it.get("name", "")).lower() == name.strip().lower():
                    del items[iid]
                    removed = True
        await ctx.send(self._t(lang, "Entfernt." if removed else "Nicht gefunden.", "Removed." if removed else "Not found."))

    @shopset.command(name="language")
    @app_commands.describe(language="Output language: de-DE or en-US")
    async def s_language(self, ctx: commands.Context, language: str) -> None:
        """Set the output language for this server."""
        language = "de-DE" if language.lower().startswith("de") else "en-US"
        await self.config.guild(ctx.guild).language.set(language)
        await ctx.send(self._t(language, "Sprache: Deutsch", "Language: English"))

    # ------------------------------------------------------------------ #
    # Dashboard: settings + item table
    # ------------------------------------------------------------------ #
    @dashboard_panel("activityshop", L("Aktivitäts-Shop", "Activity shop"), mount="guild_settings", permission="guild_admin", order=95)
    async def settings_panel(self, ctx):
        conf = self.config.guild(ctx.guild)
        lang = await conf.language()
        cur = await self._cur(ctx.guild)
        return PanelSchema(
            description=tr_lang(
                lang,
                f"Währung ({cur}) fürs Schreiben verdienen, im Shop ausgeben. Artikel im Tab 'Artikel'.",
                f"Earn currency ({cur}) for chatting, spend it in the shop. Items in the 'Items' tab.",
            ),
            fields=[
                Field.switch("enabled", L("Aktiviert", "Enabled"), value=bool(await conf.enabled())),
                Field.number("earn", L("Verdienst pro Nachricht", "Earn per message"), value=int(await conf.earn())),
                Field.number("cooldown", L("Cooldown (s)", "Cooldown (s)"), value=int(await conf.cooldown())),
                Field.select(
                    "language", L("Sprache", "Language"),
                    [{"value": "de-DE", "label": "Deutsch"}, {"value": "en-US", "label": "English"}],
                    value=str(lang), reload_on_change=True,
                ),
            ],
        )

    @settings_panel.on_submit
    async def _save_settings(self, ctx, data):
        conf = self.config.guild(ctx.guild)

        def _int(key, default):
            try:
                return int(data.get(key, default))
            except (TypeError, ValueError):
                return default

        await conf.enabled.set(bool(data.get("enabled")))
        await conf.earn.set(max(0, _int("earn", 5)))
        await conf.cooldown.set(max(0, _int("cooldown", 60)))
        lang = str(data.get("language", "en-US")).strip() or "en-US"
        await conf.language.set(lang)
        return SubmitResult.ok(tr_lang(lang, "Gespeichert.", "Saved."))

    @dashboard_list(
        "shopitems", L("Artikel", "Items"), mount="guild_settings", permission="guild_admin", order=97,
        columns=[{"key": "name", "label": "Name"}, {"key": "price", "label": "Price"}, {"key": "role", "label": "Role"}],
        description=L("Shop-Artikel. Neue im Tab 'Artikel anlegen'.", "Shop items. Add new ones in the 'Add item' tab."),
    )
    async def items_list(self, ctx):
        items = await self.config.guild(ctx.guild).items()
        rows = []
        for iid, it in items.items():
            role = ctx.guild.get_role(it.get("role")) if it.get("role") else None
            rows.append({"id": iid, "cells": {"name": str(it.get("name", "")), "price": str(it.get("price", 0)), "role": role.name if role else "—"}})
        return rows

    @items_list.edit_form
    async def items_edit_form(self, ctx, item_id):
        items = await self.config.guild(ctx.guild).items()
        it = items.get(item_id) or {}
        return PanelSchema(fields=[
            Field.text("name", L("Name", "Name"), value=str(it.get("name", ""))),
            Field.number("price", L("Preis", "Price"), value=int(it.get("price", 0))),
            Field.role("role", L("Rolle (optional)", "Role (optional)"), value=str(it.get("role") or "")),
            Field.text("desc", L("Beschreibung", "Description"), value=str(it.get("desc") or "")),
        ])

    @items_list.on_edit
    async def items_edit(self, ctx, item_id, data):
        lang = await self.config.guild(ctx.guild).language()
        role = str(data.get("role") or "").strip()
        try:
            price = int(data.get("price", 0))
        except (TypeError, ValueError):
            price = 0
        async with self.config.guild(ctx.guild).items() as items:
            it = items.get(item_id) or {}
            it["name"] = str(data.get("name") or "").strip() or it.get("name", "")
            it["price"] = max(0, price)
            it["role"] = int(role) if role.isdigit() else None
            it["desc"] = str(data.get("desc") or "").strip() or None
            items[item_id] = it
        return SubmitResult.ok(tr_lang(lang, "Artikel gespeichert.", "Item saved."))

    @items_list.on_delete
    async def items_delete(self, ctx, item_id):
        lang = await self.config.guild(ctx.guild).language()
        async with self.config.guild(ctx.guild).items() as items:
            items.pop(item_id, None)
        return SubmitResult.ok(tr_lang(lang, "Artikel gelöscht.", "Item deleted."))

    @dashboard_panel("shopitem_add", L("Artikel anlegen", "Add item"), mount="guild_settings", permission="guild_admin", order=96)
    async def item_add_panel(self, ctx):
        lang = await self.config.guild(ctx.guild).language()
        return PanelSchema(
            description=tr_lang(lang, "Neuen Shop-Artikel anlegen.", "Add a new shop item."),
            fields=[
                Field.text("name", L("Name", "Name"), value=""),
                Field.number("price", L("Preis", "Price"), value=100),
                Field.role("role", L("Rolle (optional)", "Role (optional)"), value=""),
                Field.text("desc", L("Beschreibung (optional)", "Description (optional)"), value=""),
            ],
        )

    @item_add_panel.on_submit
    async def _item_add(self, ctx, data):
        lang = await self.config.guild(ctx.guild).language()
        name = str(data.get("name") or "").strip()
        role = str(data.get("role") or "").strip()
        try:
            price = int(data.get("price", 0))
        except (TypeError, ValueError):
            price = 0
        if not name:
            return SubmitResult.fail(tr_lang(lang, "Name erforderlich.", "Name required."))
        iid = uuid.uuid4().hex[:8]
        async with self.config.guild(ctx.guild).items() as items:
            items[iid] = {"name": name, "price": max(0, price), "role": int(role) if role.isdigit() else None, "desc": str(data.get("desc") or "").strip() or None}
        return SubmitResult.ok(tr_lang(lang, "Artikel angelegt.", "Item added."), reload=True)
