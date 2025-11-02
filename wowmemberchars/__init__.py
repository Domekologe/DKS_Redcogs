from .membercharsetup import MemberCharSetup

__red_end_user_data_statement__ = "This cog stores WoW character data for members."

async def setup(bot):
    await bot.add_cog(MemberCharSetup(bot))
