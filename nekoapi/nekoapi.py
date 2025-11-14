import discord
import aiohttp
from redbot.core import commands, app_commands


BASE_URL = "https://api.nekosapi.com/v4/images/random?limit=1&rating="

VALID_RATINGS = ["safe", "suggestive", "borderline", "explicit"]


class NekoAPI(commands.Cog):
    """NekoAPI Bilder nach Rating anzeigen."""

    def __init__(self, bot):
        self.bot = bot

    # ------------------------------------------------------------------
    # Helper: API Request + Embed Builder
    # ------------------------------------------------------------------
    async def fetch_image(self, rating: str):
        async with aiohttp.ClientSession() as session:
            async with session.get(BASE_URL + rating) as resp:
                if resp.status != 200:
                    return None

                data = await resp.json()
                if not data:
                    return None

                return data[0]  # Object enthält id, url, rating

    async def build_embed(self, info: dict):
        embed = discord.Embed(
            title=f"NekoAPI – {info['rating']}",
            color=0xFF66CC
        )
        embed.set_image(url=info["url"])
        embed.set_footer(text=f"ID: {info['id']} | Rating: {info['rating']}")
        return embed

    # ------------------------------------------------------------------
    # Prefix Command
    # ------------------------------------------------------------------
    @commands.command(name="nekoapi")
    async def nekoapi_prefix(self, ctx, rating: str = "safe"):
        """Zeigt ein Bild nach Rating (default = safe)."""

        rating = rating.lower()

        if rating not in VALID_RATINGS:
            return await ctx.send(
                f"❌ Ungültiges Rating!\nErlaubt: {', '.join(VALID_RATINGS)}"
            )

        # NSFW-Check für explicit
        if rating == "explicit" and not ctx.channel.is_nsfw():
            return await ctx.send("❌ `explicit` ist nur in NSFW-Channels erlaubt.")

        info = await self.fetch_image(rating)
        if not info:
            return await ctx.send("❌ Fehler beim Abrufen der API.")

        embed = await self.build_embed(info)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # Slash: /nekoapi (fix safe)
    # ------------------------------------------------------------------
    @app_commands.command(
        name="nekoapi",
        description="Zeigt ein zufälliges Bild (rating = safe)."
    )
    async def nekoapi_slash_safe(self, interaction: discord.Interaction):
        await interaction.response.defer()

        info = await self.fetch_image("safe")
        if not info:
            return await interaction.followup.send("❌ Fehler beim Abrufen der API.")

        embed = await self.build_embed(info)
        await interaction.followup.send(embed=embed)

    # ------------------------------------------------------------------
    # Autocomplete für Rating
    # ------------------------------------------------------------------
    async def rating_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()
        return [
            app_commands.Choice(name=r, value=r)
            for r in VALID_RATINGS
            if current in r
        ]

    # ------------------------------------------------------------------
    # Slash: /nekoapi-rating <rating>
    # ------------------------------------------------------------------
    @app_commands.command(
        name="nekoapi-rating",
        description="Zeigt ein Bild mit ausgewähltem Rating."
    )
    @app_commands.describe(rating="Rating auswählen")
    @app_commands.autocomplete(rating=rating_autocomplete)
    async def nekoapi_slash_rating(self, interaction: discord.Interaction, rating: str):
        rating = rating.lower()

        await interaction.response.defer()

        if rating not in VALID_RATINGS:
            return await interaction.followup.send(
                f"❌ Ungültiges Rating! Erlaubt: {', '.join(VALID_RATINGS)}"
            )

        # NSFW-Check für explicit
        if rating == "explicit" and not interaction.channel.is_nsfw():
            return await interaction.followup.send(
                "❌ `explicit` ist nur in NSFW-Channels erlaubt."
            )

        info = await self.fetch_image(rating)
        if not info:
            return await interaction.followup.send("❌ Fehler beim Abrufen der API.")

        embed = await self.build_embed(info)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(NekoAPI(bot))
