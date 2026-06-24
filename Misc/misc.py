import discord
from discord import app_commands
from redbot.core import Config, commands

from .dks_dashboard import (
    dashboard_panel, PanelSchema, Field, SubmitResult,
    register_dashboard, unregister_dashboard,
    L, tr_lang,
)

class Misc(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=708921553002, force_registration=True)
        self.config.register_guild(language="en-US")

    async def cog_load(self) -> None:
        register_dashboard(self)

    def cog_unload(self) -> None:
        unregister_dashboard(self)

    @dashboard_panel(
        "misc_settings", L("Einstellungen", "Settings"), mount="guild_settings", permission="guild_admin"
    )
    async def misc_settings_panel(self, ctx):
        return PanelSchema(
            fields=[
                Field.select("language", L("Sprache", "Language"), [
                    {"value": "de-DE", "label": "Deutsch"},
                    {"value": "en-US", "label": "English"},
                ], value=str(await self.config.guild(ctx.guild).language()), reload_on_change=True),
            ],
        )

    @misc_settings_panel.on_submit
    async def _save_misc_settings(self, ctx, data):
        if "language" in data:
            await self.config.guild(ctx.guild).language.set("en-US" if data["language"] == "en-US" else "de-DE")
        return SubmitResult.ok()

    @app_commands.command(
        name="ping",
        description="Check if the bot is responsive.",
        extras={"i18n_desc": {
            "de-DE": "Prüft, ob der Bot reagiert.",
            "en-US": "Check if the bot is responsive.",
        }},
    )
    async def ping(self, interaction: discord.Interaction):
        lang = await self.config.guild(interaction.guild).language() if interaction.guild else "en-US"
        await interaction.response.send_message(tr_lang(lang, "Pong!", "Pong!"), ephemeral=True)
