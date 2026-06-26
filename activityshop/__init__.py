from .activityshop import ActivityShop


async def setup(bot):
    await bot.add_cog(ActivityShop(bot))
