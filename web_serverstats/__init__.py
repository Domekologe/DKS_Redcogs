from .web_serverstats import WebServerStats


async def setup(bot):
    await bot.add_cog(WebServerStats(bot))
