import discord
from redbot.core import commands, Config
from enum import IntEnum
import time


class VerificationStatus(IntEnum):
    UNVERIFIED = 0
    SOFT_VERIFIED = 1
    PASSIVE_VERIFIED = 2
    ADMIN_VERIFIED = 3


class NewUserAutomation(commands.Cog):
    """Handles new user onboarding and verification"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.config = Config.get_conf(
            self,
            identifier=928374982374,
            force_registration=True
        )

        self.config.register_member(
            verification_status=VerificationStatus.UNVERIFIED,
            characters=[],
            first_seen=None
        )

        self.config.register_guild(
            roles={
                "guest": None,
                "member_pending": None,
                "member": None
            },
            features={
                "auto_verification": True
            }
        )

    # ==================================================
    # EVENTS
    # ==================================================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Triggered when a new user joins the guild"""

        # Ignore bots
        if member.bot:
            return

        await self.config.member(member).first_seen.set(int(time.time()))
        await self.config.member(member).verification_status.set(
            VerificationStatus.UNVERIFIED
        )

        try:
            await self._send_welcome_dm(member)
        except discord.Forbidden:
            # User has DMs closed – nothing we can do
            pass

    # ==================================================
    # WELCOME FLOW
    # ==================================================

    async def _send_welcome_dm(self, member: discord.Member):
        embed = discord.Embed(
            title="Welcome!",
            description=(
                "Are you joining as a **guest** or as a **guild member**?\n\n"
                "Please choose one option below."
            ),
            color=discord.Color.blurple()
        )

        view = WelcomeChoiceView(self, member)
        await member.send(embed=embed, view=view)

    # ==================================================
    # STATE HANDLERS
    # ==================================================

    async def handle_guest(self, member: discord.Member):
        guild = member.guild
        roles = await self.config.guild(guild).roles()

        guest_role_id = roles.get("guest")
        if guest_role_id:
            role = guild.get_role(guest_role_id)
            if role:
                await member.add_roles(role, reason="Joined as guest")

    async def handle_guild_member(self, member: discord.Member):
        embed = discord.Embed(
            title="Guild Member Verification",
            description=(
                "Please enter the name of your **main character**.\n\n"
                "Example:\n`Thrall-Blackrock (EU)`"
            ),
            color=discord.Color.green()
        )

        await member.send(embed=embed)

        def check(m: discord.Message):
            return (
                m.author.id == member.id
                and isinstance(m.channel, discord.DMChannel)
            )

        try:
            msg = await self.bot.wait_for(
                "message",
                check=check,
                timeout=300
            )
        except TimeoutError:
            await member.send("⏰ Verification timed out.")
            return

        await self._process_character_input(member, msg.content)

    # ==================================================
    # CHARACTER HANDLING
    # ==================================================

    async def _process_character_input(self, member: discord.Member, raw_input: str):
        """
        Placeholder for Blizzard API validation.
        """

        # TODO: Parse name / realm / region
        # TODO: Blizzard API check

        # ---- TEMPORARY MOCK RESULT ----
        char_found = True
        in_guild = True
        # --------------------------------

        if not char_found or not in_guild:
            await member.send(
                "❌ Character not found or not in the guild. Please try again."
            )
            return

        # Save character
        await self.config.member(member).characters.set([
            {
                "raw": raw_input,
                "is_main": True,
                "verified": VerificationStatus.SOFT_VERIFIED,
                "first_seen": int(time.time()),
                "last_sync": None
            }
        ])

        await self.config.member(member).verification_status.set(
            VerificationStatus.SOFT_VERIFIED
        )

        await self._assign_pending_role(member)

        await member.send(
            "✅ Character found! You are **provisionally verified**.\n"
            "Your status will be upgraded automatically."
        )

    async def _assign_pending_role(self, member: discord.Member):
        guild = member.guild
        roles = await self.config.guild(guild).roles()

        pending_role_id = roles.get("member_pending")
        if pending_role_id:
            role = guild.get_role(pending_role_id)
            if role:
                await member.add_roles(
                    role,
                    reason="Soft verified guild member"
                )


# ==================================================
# UI VIEWS
# ==================================================

class WelcomeChoiceView(discord.ui.View):
    def __init__(self, cog: NewUserAutomation, member: discord.Member):
        super().__init__(timeout=300)
        self.cog = cog
        self.member = member

    @discord.ui.button(
        label="Guest",
        style=discord.ButtonStyle.secondary
    )
    async def guest(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer()
        await self.cog.handle_guest(self.member)
        await interaction.followup.send(
            "You have been registered as **Guest**."
        )
        self.stop()

    @discord.ui.button(
        label="Guild Member",
        style=discord.ButtonStyle.primary
    )
    async def guild_member(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.defer()
        await self.cog.handle_guild_member(self.member)
        self.stop()
