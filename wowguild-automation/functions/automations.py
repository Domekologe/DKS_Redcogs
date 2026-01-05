import time
import discord
from redbot.core import commands
from redbot.core.utils.chat_formatting import humanize_timedelta
from enum import IntEnum


class VerificationStatus(IntEnum):
    UNVERIFIED = 0
    SOFT_VERIFIED = 1
    PASSIVE_VERIFIED = 2
    ADMIN_VERIFIED = 3


class PassiveVerification(commands.Cog):
    """Handles passive character verification"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # --- CONFIG ---
        self.MIN_SUCCESSFUL_SYNCS = 2
        self.MIN_TIME_SECONDS = 12 * 60 * 60  # 12h

    # ==================================================
    # TASK LOOP
    # ==================================================

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.passive_verification_loop.is_running():
            self.passive_verification_loop.start()

    @commands.tasks.loop(hours=6)
    async def passive_verification_loop(self):
        for guild in self.bot.guilds:
            await self._process_guild(guild)

    # ==================================================
    # CORE LOGIC
    # ==================================================

    async def _process_guild(self, guild: discord.Guild):
        cog = self.bot.get_cog("NewUserAutomation")
        if not cog:
            return

        guild_config = cog.config.guild(guild)
        features = await guild_config.features()

        if not features.get("auto_verification", True):
            return

        for member in guild.members:
            if member.bot:
                continue

            await self._process_member(cog, guild, member)

    async def _process_member(
        self,
        cog,
        guild: discord.Guild,
        member: discord.Member
    ):
        member_conf = cog.config.member(member)
        status = VerificationStatus(
            await member_conf.verification_status()
        )

        if status != VerificationStatus.SOFT_VERIFIED:
            return

        characters = await member_conf.characters()
        if not characters:
            return

        char = characters[0]  # Mainchar only (by design)

        # --------------------------------------------------
        # Blizzard API CHECK (PLACEHOLDER)
        # --------------------------------------------------
        # This MUST be replaced with:
        # await blizzard.is_character_in_guild(...)
        char_still_in_guild = True
        # --------------------------------------------------

        if not char_still_in_guild:
            return

        # Update sync info
        now = int(time.time())
        char.setdefault("sync_count", 0)
        char["sync_count"] += 1
        char["last_sync"] = now

        await member_conf.characters.set([char])

        # Check upgrade conditions
        first_seen = char.get("first_seen", now)
        time_passed = now - first_seen

        if (
            char["sync_count"] >= self.MIN_SUCCESSFUL_SYNCS
            and time_passed >= self.MIN_TIME_SECONDS
        ):
            await self._upgrade_member(cog, guild, member)

    # ==================================================
    # UPGRADE HANDLING
    # ==================================================

    async def _upgrade_member(
        self,
        cog,
        guild: discord.Guild,
        member: discord.Member
    ):
        await cog.config.member(member).verification_status.set(
            VerificationStatus.PASSIVE_VERIFIED
        )

        roles = await cog.config.guild(guild).roles()

        pending_id = roles.get("member_pending")
        member_id = roles.get("member")

        if pending_id:
            role = guild.get_role(pending_id)
            if role:
                await member.remove_roles(
                    role,
                    reason="Passive verification completed"
                )

        if member_id:
            role = guild.get_role(member_id)
            if role:
                await member.add_roles(
                    role,
                    reason="Passive verification completed"
                )

        try:
            await member.send(
                "✅ Your guild membership has been **fully verified**.\n"
                "Thank you for your patience!"
            )
        except discord.Forbidden:
            pass
