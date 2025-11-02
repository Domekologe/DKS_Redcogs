from redbot.core import commands, Config
from redbot.core.bot import Red
from redbot.core.utils.chat_formatting import humanize_list
from AAA3A_utils.cogsutils import DashboardIntegration

import discord


class SetupNewMember(commands.Cog):
    """Setup system for new members joining with a specific role."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=6942069, force_registration=True)

        default_guild = {
            "enabled": False,
            "role_id": None,
            "language": "en",  # "en" or "de"
            "members": {},  # {user_id: {"main": "Char", "twinks": ["Twink1", "Twink2"]}}
        }
        self.config.register_guild(**default_guild)

        # AAA3A Dashboard integration
        self.dashboard_integration = DashboardIntegration(self)

    async def cog_load(self):
        await self.dashboard_integration.init()

    async def cog_unload(self):
        await self.dashboard_integration.deinit()

    # ─────────────────────────────────────────────
    # Slash Commands
    # ─────────────────────────────────────────────

    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @commands.hybrid_command(name="setup-newmember")
    async def setup_newmember(
        self, ctx: commands.Context, enabled: bool, role: discord.Role = None, language: str = "en"
    ):
        """Enable or disable the new member setup system."""
        await self.config.guild(ctx.guild).enabled.set(enabled)
        await self.config.guild(ctx.guild).role_id.set(role.id if role else None)
        await self.config.guild(ctx.guild).language.set(language.lower())

        await ctx.send(
            f"✅ SetupNewMember system {'enabled' if enabled else 'disabled'}.\n"
            f"Role: {role.mention if role else 'None'}\n"
            f"Language: {'English' if language.lower() == 'en' else 'Deutsch'}"
        )

    @commands.hybrid_command(name="getmemberchars")
    async def get_member_chars(self, ctx: commands.Context):
        """List all members and their registered characters."""
        members = await self.config.guild(ctx.guild).members()
        if not members:
            return await ctx.send("❌ No member data found.")

        lines = []
        for user_id, data in members.items():
            user = ctx.guild.get_member(int(user_id))
            if not user:
                continue
            main = data.get("main", "❌ No main set")
            twinks = data.get("twinks", [])
            line = f"**{user.display_name}** → {main} (Main)"
            if twinks:
                line += f", {humanize_list(twinks)} (Twinks)"
            lines.append(line)

        if not lines:
            await ctx.send("❌ No active members found.")
        else:
            await ctx.author.send("\n".join(lines))
            await ctx.send("📩 Sent you a DM with all member characters.")

    @commands.hybrid_command(name="setmainchar")
    async def set_main_char(self, ctx: commands.Context, *, name: str):
        """Set your main character name."""
        guild_data = self.config.guild(ctx.guild)
        members = await guild_data.members()
        user_data = members.get(str(ctx.author.id), {"main": None, "twinks": []})
        user_data["main"] = name
        members[str(ctx.author.id)] = user_data
        await guild_data.members.set(members)
        await ctx.send(f"✅ Your main character is now set to **{name}**.")

    @commands.hybrid_command(name="settwinkchar")
    async def set_twink_char(self, ctx: commands.Context, *, name: str):
        """Add a twink character."""
        guild_data = self.config.guild(ctx.guild)
        members = await guild_data.members()
        user_data = members.get(str(ctx.author.id), {"main": None, "twinks": []})
        user_data["twinks"].append(name)
        members[str(ctx.author.id)] = user_data
        await guild_data.members.set(members)
        await ctx.send(f"✅ Added **{name}** as a twink character.")

    # ─────────────────────────────────────────────
    # Listener: Role assignment event
    # ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild
        enabled = await self.config.guild(guild).enabled()
        if not enabled:
            return

        role_id = await self.config.guild(guild).role_id()
        if not role_id:
            return

        # Detect if the role was newly added
        before_roles = {r.id for r in before.roles}
        after_roles = {r.id for r in after.roles}
        if role_id in after_roles and role_id not in before_roles:
            lang = await self.config.guild(guild).language()
            msg = {
                "en": "Welcome! What is your **main character name**?",
                "de": "Willkommen! Wie heißt dein **Hauptcharakter**?",
            }[lang]

            try:
                await after.send(msg)
            except discord.Forbidden:
                return

            def check(m):
                return m.author == after and isinstance(m.channel, discord.DMChannel)

            try:
                message = await self.bot.wait_for("message", check=check, timeout=120)
                members = await self.config.guild(guild).members()
                members[str(after.id)] = {"main": message.content, "twinks": []}
                await self.config.guild(guild).members.set(members)
                await after.send("✅ Got it! Your main character has been saved.")
            except TimeoutError:
                await after.send("⏰ Timeout — please use `/setmainchar` later.")

    # ─────────────────────────────────────────────
    # Dashboard Endpoints
    # ─────────────────────────────────────────────

    @DashboardIntegration.endpoint()
    async def get_guild_settings(self, request):
        """Return guild settings for dashboard."""
        guild_id = int(request.match_info["guild_id"])
        data = await self.config.guild_from_id(guild_id).all()
        return {"status": "ok", "data": data}

