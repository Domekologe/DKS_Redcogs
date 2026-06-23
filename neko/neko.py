import discord
import aiohttp
from redbot.core import commands, app_commands

from .dks_dashboard import (
    register_dashboard, unregister_dashboard,
)

BASE_URL = "https://nekos.best/api/v2/"

IMAGE_CATEGORIES = [
    "husbando", "kitsune", "neko", "waifu"
]

GIF_CATEGORIES = [
    "angry", "baka", "bite", "blush", "bored", "cry", "cuddle", "dance", "facepalm",
    "feed", "handhold", "handshake", "happy", "highfive", "hug", "kick", "kiss",
    "laugh", "lurk", "nod", "nom", "nope", "pat", "peck", "poke", "pout", "punch",
    "run", "shoot", "shrug", "slap", "sleep", "smile", "smug", "stare", "think",
    "thumbsup", "tickle", "wave", "wink", "yawn", "yeet"
]

ALL_CATEGORIES = IMAGE_CATEGORIES + GIF_CATEGORIES


class Neko(commands.Cog):
    """Zeigt Neko-Bilder und GIFs von nekos.best an."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self) -> None:
        register_dashboard(self)

    def cog_unload(self) -> None:
        unregister_dashboard(self)

    # ------------------------------------------------------------------
    # Helper: API Request + Embed Builder
    # ------------------------------------------------------------------
    async def fetch_and_build_embed(self, category: str):
        url = BASE_URL + category

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return discord.Embed(
                        title="Fehler",
                        description="Konnte keine Daten abrufen.",
                        color=0xFF0000
                    )
                data = await resp.json()

        result = data["results"][0]
        img = result["url"]
        artist = result.get("artist_name", "Unbekannt")
        source = result.get("source_url", "Keine Quelle")

        embed = discord.Embed(
            title=f"{category.capitalize()}",
            color=0xFF66CC
        )
        embed.set_image(url=img)
        embed.set_footer(text=f"Artist: {artist} | Source: {source}")

        return embed

    # ------------------------------------------------------------------
    # Prefix command: !neko → only category "neko"
    # Prefix command: !neko <category> → any category
    # ------------------------------------------------------------------
    @commands.command(name="neko")
    async def neko_prefix(self, ctx, category: str = None):
        """Zeigt ein Neko oder aus der Kategorie ein Bild/GIF."""

        # No parameter → always category "neko"
        if category is None:
            embed = await self.fetch_and_build_embed("neko")
            return await ctx.send(embed=embed)

        category = category.lower()

        if category not in ALL_CATEGORIES:
            return await ctx.send(
                f"❌ Ungültige Kategorie!\nVerfügbar: `{', '.join(ALL_CATEGORIES)}`"
            )

        embed = await self.fetch_and_build_embed(category)
        await ctx.send(embed=embed)


    # ------------------------------------------------------------------
    # Autocomplete function
    # ------------------------------------------------------------------
    async def neko_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()

        suggestions = [
            app_commands.Choice(name=cat, value=cat)
            for cat in ALL_CATEGORIES
            if current in cat.lower()
        ]

        return suggestions[:25]

    # ------------------------------------------------------------------
    # Slash command: /neko → only category "neko"
    # ------------------------------------------------------------------
    @app_commands.command(name="neko", description="Zeigt ein Neko-Bild.")
    async def neko_slash(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = await self.fetch_and_build_embed("neko")
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # Slash command: /neko-cat <category> → any category
    # ------------------------------------------------------------------
    @app_commands.command(
        name="neko-cat",
        description="Zeigt ein Bild oder GIF aus einer Kategorie."
    )
    @app_commands.describe(category="Kategorie auswählen")
    @app_commands.autocomplete(category=neko_autocomplete)
    async def neko_cat_slash(self, interaction: discord.Interaction, category: str):
        await interaction.response.defer()
        embed = await self.fetch_and_build_embed(category)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Neko(bot))
