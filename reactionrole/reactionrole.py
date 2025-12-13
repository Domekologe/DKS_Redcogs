import discord
from redbot.core import commands, Config
import uuid

class ReactionRole(commands.Cog):
    """Simple ReactionRole Cog"""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=983472983472, force_registration=True)
        self.config.register_guild(reactionroles={})

    # -------------------------
    # SET
    # -------------------------
    @commands.hybrid_command(name="reactionrole-set")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def reactionrole_set(
        self,
        ctx: commands.Context,
        message_id: int,
        emoji: str,
        role: discord.Role
    ):
        guild = ctx.guild
        channel = ctx.channel

        try:
            message = await channel.fetch_message(message_id)
        except discord.NotFound:
            return await ctx.send("❌ Message nicht gefunden.")
        except discord.Forbidden:
            return await ctx.send("❌ Keine Rechte, um die Nachricht zu lesen.")

        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            return await ctx.send("❌ Ungültiges Emoji oder keine Rechte.")

        rr_id = str(uuid.uuid4())[:8]

        async with self.config.guild(guild).reactionroles() as data:
            data[rr_id] = {
                "message_id": message_id,
                "channel_id": channel.id,
                "emoji": str(emoji),
                "role_id": role.id
            }

        await ctx.send(
            f"✅ ReactionRole erstellt\n"
            f"**ID:** `{rr_id}`\n"
            f"Emoji: {emoji}\n"
            f"Rolle: {role.mention}"
        )

    # -------------------------
    # REMOVE
    # -------------------------
    @commands.hybrid_command(name="reactionrole-remove")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def reactionrole_remove(self, ctx: commands.Context, rr_id: str):
        async with self.config.guild(ctx.guild).reactionroles() as data:
            if rr_id not in data:
                return await ctx.send("❌ Diese ReactionRole-ID existiert nicht.")

            del data[rr_id]

        await ctx.send(f"🗑️ ReactionRole `{rr_id}` entfernt.")

    # -------------------------
    # GET
    # -------------------------
    @commands.hybrid_command(name="reactionrole-get")
    @commands.guild_only()
    async def reactionrole_get(self, ctx: commands.Context):
        data = await self.config.guild(ctx.guild).reactionroles()

        if not data:
            return await ctx.send("ℹ️ Keine ReactionRoles vorhanden.")

        lines = []
        for rr_id, entry in data.items():
            role = ctx.guild.get_role(entry["role_id"])
            lines.append(
                f"**ID:** `{rr_id}` | "
                f"Emoji: {entry['emoji']} | "
                f"Rolle: {role.name if role else '❌ gelöscht'} | "
                f"MessageID: `{entry['message_id']}`"
            )

        await ctx.send("\n".join(lines))

    # -------------------------
    # EVENTS
    # -------------------------
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)

        if member is None or member.bot:
            return

        data = await self.config.guild(guild).reactionroles()

        for entry in data.values():
            if (
                payload.message_id == entry["message_id"]
                and str(payload.emoji) == entry["emoji"]
            ):
                role = guild.get_role(entry["role_id"])
                if role:
                    await member.add_roles(role, reason="ReactionRole")
                break

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.guild_id is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        member = guild.get_member(payload.user_id)

        if member is None or member.bot:
            return

        data = await self.config.guild(guild).reactionroles()

        for entry in data.values():
            if (
                payload.message_id == entry["message_id"]
                and str(payload.emoji) == entry["emoji"]
            ):
                role = guild.get_role(entry["role_id"])
                if role:
                    await member.remove_roles(role, reason="ReactionRole")
                break

    @commands.hybrid_command(name="reactionrole-sync")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True)
    async def reactionrole_sync(self, ctx: commands.Context):
        guild = ctx.guild
        data = await self.config.guild(guild).reactionroles()

        if not data:
            return await ctx.send("ℹ️ Keine ReactionRoles zum Synchronisieren.")

        added = 0

        for rr_id, entry in data.items():
            channel = guild.get_channel(entry["channel_id"])
            if not channel:
                continue

            try:
                message = await channel.fetch_message(entry["message_id"])
            except (discord.NotFound, discord.Forbidden):
                continue

            role = guild.get_role(entry["role_id"])
            if not role:
                continue

            reaction = discord.utils.get(
                message.reactions,
                emoji=entry["emoji"]
            )

            if not reaction:
                continue

            async for user in reaction.users():
                if user.bot:
                    continue

                member = guild.get_member(user.id)
                if not member:
                    continue

                if role not in member.roles:
                    await member.add_roles(
                        role,
                        reason="ReactionRole manual sync"
                    )
                    added += 1

        await ctx.send(
            f"🔄 Synchronisation abgeschlossen\n"
            f"➕ Rollen neu gesetzt: **{added}**"
        )
