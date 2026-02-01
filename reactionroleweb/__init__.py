from .reactionroleweb import ReactionRoleWeb

async def setup(bot):
    await bot.add_cog(ReactionRoleWeb(bot))
