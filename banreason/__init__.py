from .banreason import BanReason


async def setup(bot):
    await bot.add_cog(BanReason(bot))
