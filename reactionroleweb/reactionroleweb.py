import discord
from redbot.core import commands, Config
from typing import Dict, List, Optional, Any
import uuid
import logging

log = logging.getLogger("red.dks_redcogs.reactionroleweb")


class ReactionRoleWeb(commands.Cog):
    """Web interface for ReactionRole system via AAA3A Dashboard"""

    def __init__(self, bot):
        self.bot = bot
        # Use the same config identifier as the original reactionrole cog for compatibility
        self.config = Config.get_conf(self, identifier=983472983472, force_registration=True)
        self.config.register_guild(reactionroles={})
        self._dashboard_integration_ready = False

    async def cog_load(self):
        """Called when the cog is loaded"""
        await self._register_to_dashboard()

    async def cog_unload(self):
        """Called when the cog is unloaded"""
        await self._unregister_from_dashboard()

    @commands.Cog.listener()
    async def on_cog_load(self, cog: commands.Cog):
        """Called when a cog is loaded"""
        if cog.qualified_name == "Dashboard":
            await self._register_to_dashboard()

    async def _register_to_dashboard(self):
        """Register this cog as a third-party integration with the Dashboard"""
        # Wait a bit to ensure things are ready
        await self.bot.wait_until_red_ready()
        
        dashboard_cog = self.bot.get_cog("Dashboard")
        if not dashboard_cog:
            # We don't log a warning here if called from on_cog_load only for specific calls
            # But initial load we might want to know. 
            # If this is called from cog_load, we log if missing.
            # If called from on_cog_load(Dashboard), it must exist.
            return

        if self._dashboard_integration_ready:
            return

        try:
            # The Dashboard cog uses a decorator-based system for third-party integrations
            # We need to register our methods directly with the dashboard's third-party system
            if hasattr(dashboard_cog, 'rpc') and dashboard_cog.rpc:
                # Check if third_parties_handler exists
                if hasattr(dashboard_cog.rpc, 'third_parties_handler'):
                    handler = dashboard_cog.rpc.third_parties_handler
                    
                    # Try to find the correct method signature
                    if hasattr(handler, 'add_third_party'):
                        try:
                            # Try with positional argument (most standard)
                            handler.add_third_party(self)
                        except TypeError:
                            try:
                                # Try with 'cog' kwarg
                                handler.add_third_party(cog=self)
                            except TypeError:
                                # If it requires detailed arguments
                                handler.add_third_party(
                                    cog=self,
                                    name="ReactionRoles",
                                    description="Manage reaction roles"
                                )
                        
                        self._dashboard_integration_ready = True
                        log.info("Successfully registered ReactionRoleWeb as a third-party integration with Dashboard")
                    
                    # Fallback or additional Check: manual dictionary insertion if the method doesn't exist/work
                    elif hasattr(handler, 'third_parties'):
                        handler.third_parties["reactionrole"] = {
                            "name": "Reaction Roles",
                            "description": "Manage reaction roles for your server through an easy-to-use web interface",
                            "cog": self
                        }
                        self._dashboard_integration_ready = True
                        log.info("Successfully registered ReactionRoleWeb (direct registration) with Dashboard")
                    else:
                        log.error("Dashboard third_parties_handler found but no registration method available")
                else:
                    log.error("Dashboard RPC found but third_parties_handler not available")
            else:
                log.error("Dashboard cog found but RPC not available - make sure bot is started with --rpc flag")
        except Exception as e:
            log.error(f"Failed to register with Dashboard: {e}", exc_info=True)

    async def _unregister_from_dashboard(self):
        """Unregister this cog from the Dashboard"""
        dashboard_cog = self.bot.get_cog("Dashboard")
        if dashboard_cog and hasattr(dashboard_cog, 'rpc') and hasattr(dashboard_cog.rpc, 'third_parties_handler'):
            try:
                if hasattr(dashboard_cog.rpc.third_parties_handler, 'remove_third_party'):
                     dashboard_cog.rpc.third_parties_handler.remove_third_party("ReactionRoleWeb") # Try class name
                     # The remove_third_party often takes the cog name
                elif hasattr(dashboard_cog.rpc.third_parties_handler, 'third_parties'):
                     if "reactionrole" in dashboard_cog.rpc.third_parties_handler.third_parties:
                         del dashboard_cog.rpc.third_parties_handler.third_parties["reactionrole"]
                
                log.info("Successfully unregistered ReactionRoleWeb from Dashboard")
            except Exception as e:
                log.error(f"Failed to unregister from Dashboard: {e}", exc_info=True)

    # -------------------------
    # RPC Methods for Dashboard
    # -------------------------

    def _dashboard_page(name: str, description: str, methods: List[str] = None):
        """Decorator to mark a method as a dashboard page"""
        if methods is None:
            methods = ["GET", "POST"]
            
        def decorator(func):
            func.__dashboard_params__ = {
                "name": name,
                "description": description,
                "methods": methods
            }
            return func
        return decorator

    @_dashboard_page(name="get_reactionroles", description="Get all reaction roles for a guild", methods=["GET"])
    async def rpc_get_reactionroles(self, guild_id: int, **kwargs) -> Dict[str, Any]:
        """
        Get all reaction roles for a guild
        
        Args:
            guild_id: The guild ID
            
        Returns:
            Dict with 'success' status and 'data' containing reaction roles
        """
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return {"success": False, "error": "Guild not found"}

            data = await self.config.guild(guild).reactionroles()
            
            # Enrich data with current role and channel information
            enriched_data = {}
            for rr_id, entry in data.items():
                role = guild.get_role(entry["role_id"])
                channel = guild.get_channel(entry["channel_id"])
                
                enriched_data[rr_id] = {
                    "id": rr_id,
                    "message_id": entry["message_id"],
                    "channel_id": entry["channel_id"],
                    "channel_name": channel.name if channel else "❌ Deleted",
                    "emoji": entry["emoji"],
                    "role_id": entry["role_id"],
                    "role_name": role.name if role else "❌ Deleted",
                    "role_exists": role is not None,
                    "channel_exists": channel is not None
                }

            return {"success": True, "data": enriched_data}
        except Exception as e:
            log.error(f"Error in rpc_get_reactionroles: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @_dashboard_page(name="add_reactionrole", description="Add a new reaction role", methods=["POST"])
    async def rpc_add_reactionrole(
        self, 
        guild_id: int, 
        channel_id: int, 
        message_id: int, 
        emoji: str, 
        role_id: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Add a new reaction role
        
        Args:
            guild_id: The guild ID
            channel_id: The channel ID where the message is
            message_id: The message ID to add the reaction to
            emoji: The emoji to use
            role_id: The role ID to assign
            
        Returns:
            Dict with 'success' status and created reaction role data
        """
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return {"success": False, "error": "Guild not found"}

            channel = guild.get_channel(channel_id)
            if not channel:
                return {"success": False, "error": "Channel not found"}

            role = guild.get_role(role_id)
            if not role:
                return {"success": False, "error": "Role not found"}

            # Fetch the message
            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                return {"success": False, "error": "Message not found"}
            except discord.Forbidden:
                return {"success": False, "error": "No permission to read message"}

            # Try to add the reaction
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException as e:
                return {"success": False, "error": f"Invalid emoji or no permission: {str(e)}"}

            # Generate unique ID
            rr_id = str(uuid.uuid4())[:8]

            # Save to config
            async with self.config.guild(guild).reactionroles() as data:
                data[rr_id] = {
                    "message_id": message_id,
                    "channel_id": channel_id,
                    "emoji": str(emoji),
                    "role_id": role_id
                }

            return {
                "success": True,
                "data": {
                    "id": rr_id,
                    "message_id": message_id,
                    "channel_id": channel_id,
                    "channel_name": channel.name,
                    "emoji": str(emoji),
                    "role_id": role_id,
                    "role_name": role.name
                }
            }
        except Exception as e:
            log.error(f"Error in rpc_add_reactionrole: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @_dashboard_page(name="remove_reactionrole", description="Remove a reaction role", methods=["POST"])
    async def rpc_remove_reactionrole(self, guild_id: int, rr_id: str, **kwargs) -> Dict[str, Any]:
        """
        Remove a reaction role
        
        Args:
            guild_id: The guild ID
            rr_id: The reaction role ID to remove
            
        Returns:
            Dict with 'success' status
        """
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return {"success": False, "error": "Guild not found"}

            async with self.config.guild(guild).reactionroles() as data:
                if rr_id not in data:
                    return {"success": False, "error": "Reaction role not found"}
                
                del data[rr_id]

            return {"success": True, "message": f"Reaction role {rr_id} removed"}
        except Exception as e:
            log.error(f"Error in rpc_remove_reactionrole: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @_dashboard_page(name="sync_reactionroles", description="Synchronize all reaction roles", methods=["POST"])
    async def rpc_sync_reactionroles(self, guild_id: int, **kwargs) -> Dict[str, Any]:
        """
        Synchronize all reaction roles (add roles to users who already reacted)
        
        Args:
            guild_id: The guild ID
            
        Returns:
            Dict with 'success' status and number of roles added
        """
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return {"success": False, "error": "Guild not found"}

            data = await self.config.guild(guild).reactionroles()
            
            if not data:
                return {"success": True, "added": 0, "message": "No reaction roles to synchronize"}

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

                reaction = discord.utils.get(message.reactions, emoji=entry["emoji"])
                if not reaction:
                    continue

                async for user in reaction.users():
                    if user.bot:
                        continue

                    member = guild.get_member(user.id)
                    if not member:
                        continue

                    if role not in member.roles:
                        await member.add_roles(role, reason="ReactionRole manual sync")
                        added += 1

            return {
                "success": True,
                "added": added,
                "message": f"Synchronization complete. Added {added} roles."
            }
        except Exception as e:
            log.error(f"Error in rpc_sync_reactionroles: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @_dashboard_page(name="get_channels", description="Get all text channels in a guild", methods=["GET"])
    async def rpc_get_channels(self, guild_id: int, **kwargs) -> Dict[str, Any]:
        """
        Get all text channels in a guild
        
        Args:
            guild_id: The guild ID
            
        Returns:
            Dict with 'success' status and list of channels
        """
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return {"success": False, "error": "Guild not found"}

            channels = [
                {
                    "id": channel.id,
                    "name": channel.name,
                    "category": channel.category.name if channel.category else "No Category"
                }
                for channel in guild.text_channels
                if channel.permissions_for(guild.me).read_messages
            ]

            return {"success": True, "data": channels}
        except Exception as e:
            log.error(f"Error in rpc_get_channels: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @_dashboard_page(name="get_roles", description="Get all roles in a guild", methods=["GET"])
    async def rpc_get_roles(self, guild_id: int, **kwargs) -> Dict[str, Any]:
        """
        Get all roles in a guild
        
        Args:
            guild_id: The guild ID
            
        Returns:
            Dict with 'success' status and list of roles
        """
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return {"success": False, "error": "Guild not found"}

            # Filter out @everyone and roles higher than bot's highest role
            bot_top_role = guild.me.top_role
            roles = [
                {
                    "id": role.id,
                    "name": role.name,
                    "color": str(role.color),
                    "position": role.position,
                    "manageable": role < bot_top_role
                }
                for role in guild.roles
                if role != guild.default_role  # Exclude @everyone
            ]
            
            # Sort by position (highest first)
            roles.sort(key=lambda r: r["position"], reverse=True)

            return {"success": True, "data": roles}
        except Exception as e:
            log.error(f"Error in rpc_get_roles: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    @_dashboard_page(name="get_message", description="Get message details", methods=["GET"])
    async def rpc_get_message(
        self, 
        guild_id: int, 
        channel_id: int, 
        message_id: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Get message details
        
        Args:
            guild_id: The guild ID
            channel_id: The channel ID
            message_id: The message ID
            
        Returns:
            Dict with 'success' status and message data
        """
        try:
            guild = self.bot.get_guild(guild_id)
            if not guild:
                return {"success": False, "error": "Guild not found"}

            channel = guild.get_channel(channel_id)
            if not channel:
                return {"success": False, "error": "Channel not found"}

            try:
                message = await channel.fetch_message(message_id)
            except discord.NotFound:
                return {"success": False, "error": "Message not found"}
            except discord.Forbidden:
                return {"success": False, "error": "No permission to read message"}

            return {
                "success": True,
                "data": {
                    "id": message.id,
                    "content": message.content[:100] + "..." if len(message.content) > 100 else message.content,
                    "author": str(message.author),
                    "created_at": message.created_at.isoformat(),
                    "reactions": [str(reaction.emoji) for reaction in message.reactions]
                }
            }
        except Exception as e:
            log.error(f"Error in rpc_get_message: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    # -------------------------
    # Status Command
    # -------------------------

    @commands.command(name="reactionroleweb-status")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def status(self, ctx: commands.Context):
        """Check the status of ReactionRoleWeb integration"""
        dashboard_cog = self.bot.get_cog("Dashboard")
        
        if not dashboard_cog:
            await ctx.send(
                "❌ **Dashboard cog not found**\n"
                "Please install and load the Dashboard cog from AAA3A-cogs:\n"
                "`[p]repo add AAA3A-cogs https://github.com/AAA3A-AAA3A/AAA3A-cogs`\n"
                "`[p]cog install AAA3A-cogs dashboard`\n"
                "`[p]load dashboard`"
            )
            return

        if self._dashboard_integration_ready:
            await ctx.send(
                "✅ **ReactionRoleWeb is active**\n"
                f"Dashboard integration: Active\n"
                f"Access the web interface through your Dashboard at `/third-party/reactionrole`"
            )
        else:
            await ctx.send(
                "⚠️ **ReactionRoleWeb loaded but integration not ready**\n"
                "The Dashboard cog is loaded but the RPC integration failed.\n"
                "Try reloading this cog: `[p]reload reactionroleweb`"
            )
