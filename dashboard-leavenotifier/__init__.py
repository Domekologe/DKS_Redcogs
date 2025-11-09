from .leavenotifier import LeaveNotifier

async def setup(bot):
    await bot.add_cog(LeaveNotifier(bot))
