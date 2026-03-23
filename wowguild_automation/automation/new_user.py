from typing import Dict, Optional

import discord
from discord.ext import commands

from ..functions.automations import RankSyncService

TEXTS: Dict[str, Dict[str, str]] = {
    "de-DE": {
        "lang_prompt": "Willkommen! Bitte waehle deine Sprache: `de` oder `en`.",
        "lang_timeout": "Onboarding abgebrochen (Zeit abgelaufen).",
        "role_prompt": "Bist du **Gast** oder **neues Gildenmitglied**? Antworte mit `gast` oder `mitglied`.",
        "guest_done": "Du wurdest als Gast markiert. Bitte lies trotzdem die Regeln und bestaetige sie.",
        "mainchar_prompt": "Bitte nenne deinen Mainchar Namen.",
        "mainchar_timeout": "Kein Mainchar erhalten, Onboarding beendet.",
        "verified": "Verifizierung erfolgreich. Mainchar `{main}` gefunden, Ingame-Rang `{rank}`.",
        "manual": "Automatische Verifizierung nicht moeglich. Das Team wurde fuer manuelle Pruefung benachrichtigt.",
        "rules": "Wichtig: Bitte lies die Serverregeln und bestaetige sie mit dem vorgegebenen Emoji.",
    },
    "en-US": {
        "lang_prompt": "Welcome! Please choose your language: `de` or `en`.",
        "lang_timeout": "Onboarding cancelled (timeout).",
        "role_prompt": "Are you a **guest** or a **new guild member**? Reply with `guest` or `member`.",
        "guest_done": "You are marked as a guest. Please still read and confirm the server rules.",
        "mainchar_prompt": "Please send your main character name.",
        "mainchar_timeout": "No main character received, onboarding cancelled.",
        "verified": "Verification successful. Main character `{main}` found, ingame rank `{rank}`.",
        "manual": "Automatic verification failed. The team was notified for manual review.",
        "rules": "Important: Please read the server rules and confirm with the required emoji.",
    },
}


async def handle_new_member_onboarding(
    bot: commands.Bot,
    member: discord.Member,
    guild_config: dict,
    rank_sync: RankSyncService,
    manual_channel: Optional[discord.TextChannel],
) -> str:
    # Onboarding in DM to keep answers private.
    dm = await member.create_dm()

    def check(message: discord.Message) -> bool:
        return message.author.id == member.id and isinstance(message.channel, discord.DMChannel)

    await dm.send(TEXTS["de-DE"]["lang_prompt"] + "\n" + TEXTS["en-US"]["lang_prompt"])
    try:
        lang_reply = await bot.wait_for("message", check=check, timeout=180)
    except Exception:
        await dm.send(TEXTS["de-DE"]["lang_timeout"])
        return "de-DE"

    lang_content = lang_reply.content.lower().strip()
    lang = "en-US" if lang_content.startswith("en") else "de-DE"
    t = TEXTS[lang]

    await dm.send(t["role_prompt"])
    try:
        reply = await bot.wait_for("message", check=check, timeout=180)
    except Exception:
        await dm.send(t["lang_timeout"])
        return lang

    roles = guild_config.get("roles", {})
    guest_role = member.guild.get_role(roles.get("guest_role_id", 0))
    member_role = member.guild.get_role(roles.get("member_role_id", 0))

    is_guest = "gast" in reply.content.lower() or "guest" in reply.content.lower()
    if is_guest:
        if guest_role:
            await member.add_roles(guest_role, reason="WoW onboarding: guest")
        await dm.send(t["guest_done"])
        return lang

    await dm.send(t["mainchar_prompt"])
    try:
        char_reply = await bot.wait_for("message", check=check, timeout=300)
    except Exception:
        await dm.send(t["mainchar_timeout"])
        return lang

    main_char = char_reply.content.strip()
    rank = await rank_sync.sync_member_rank(member, guild_config, main_char)
    if rank:
        if member_role and member_role not in member.roles:
            await member.add_roles(member_role, reason="WoW onboarding: verified guild member")
        await dm.send(t["verified"].format(main=main_char, rank=rank))
    else:
        template = guild_config.get("templates", {}).get(
            "manual_verification",
            "Manuelle Verifizierung nötig! User {username} hat sich gemeldet als Char {charname}.",
        )
        if manual_channel:
            await manual_channel.send(
                template.format(username=member.display_name, charname=main_char)
            )
        await dm.send(t["manual"])

    await dm.send(t["rules"])
    return lang

