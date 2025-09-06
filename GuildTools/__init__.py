from .guildtools import GuildTools
from .pollexport import GuildToolsPollExport

async def setup(bot):
    await bot.add_cog(GuildTools(bot))
    await bot.add_cog(GuildToolsPollExport(bot))
