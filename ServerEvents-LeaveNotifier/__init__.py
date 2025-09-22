from .LeaveNotifier import ServerEventsLeaveNotifier

async def setup(bot):
    await bot.add_cog(ServerEventsLeaveNotifier(bot))
