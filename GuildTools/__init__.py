from .guildtools import GuildTools

async def setup(bot):
    await bot.add_cog(GuildTools(bot))
