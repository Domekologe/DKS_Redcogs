# guildtools/pollexport.py
import io
from typing import Dict, List, Set, Tuple, Optional

import discord
from discord import app_commands
from redbot.core import commands

# ---- kleine Helper: REST-Call für Voter holen (paged) ----
async def fetch_answer_voters(client: discord.Client, channel_id: int, message_id: int, answer_id: int, limit: int = 1000) -> List[int]:
    """Liefert User-IDs, die für 'answer_id' gestimmt haben. Handhabt Pagination via 'after'."""
    user_ids: List[int] = []
    after: Optional[int] = None
    fetched = 0

    while True:
        # discord API: GET /channels/{channel_id}/polls/{message_id}/answers/{answer_id}/voters
        # discord.py stellt das i.d.R. als http.get_poll_answer_voters bereit; wenn nicht, Route selbst bauen.
        try:
            data = await client.http.get_poll_answer_voters(channel_id, message_id, answer_id, limit=min(100, limit - fetched), after=after)
        except AttributeError:
            # Fallback auf generische Route
            route = discord.http.Route(
                'GET',
                '/channels/{channel_id}/polls/{message_id}/answers/{answer_id}/voters',
                channel_id=channel_id, message_id=message_id, answer_id=answer_id
            )
            params = {'limit': min(100, limit - fetched)}
            if after:
                params['after'] = after
            data = await client.http.request(route, params=params)

        users = data.get('users', []) if isinstance(data, dict) else data  # je nach lib-Version
        if not users:
            break

        ids = []
        for u in users:
            # kann 'id' (Snowflake) sein oder kompletter User
            uid = int(u['id'] if isinstance(u, dict) else int(u))
            ids.append(uid)
        user_ids.extend(ids)
        fetched += len(ids)

        if len(ids) < 100 or fetched >= limit:
            break
        after = ids[-1]

    return user_ids


class GuildToolsPollExport(commands.Cog):
    """Export nativer Discord-Umfragen als CSV (;-getrennt)."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.describe(
        poll="Wähle die Umfrage (Autocomplete: letzte Polls im Channel)",
        type="Export-Ansicht"
    )
    @app_commands.choices(
        type=[
            app_commands.Choice(name="Key-Oriented", value="key"),
            app_commands.Choice(name="Value-Oriented", value="value"),
        ]
    )
    @app_commands.command(name="export-poll", description="Exportiert eine native Discord-Umfrage als CSV (;-getrennt).")
    async def export_poll(self, interaction: discord.Interaction, poll: str, type: app_commands.Choice[str]):
        await interaction.response.defer(thinking=True)

        # Erwartet message_id als String (aus Autocomplete)
        try:
            message_id = int(poll)
        except ValueError:
            return await interaction.followup.send("❌ Ungültige Umfrage-Auswahl.", ephemeral=True)

        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
            return await interaction.followup.send("❌ Dieser Befehl funktioniert nur in Textchannels/Threads.", ephemeral=True)

        try:
            msg = await channel.fetch_message(message_id)
        except discord.NotFound:
            return await interaction.followup.send("❌ Nachricht nicht gefunden.", ephemeral=True)

        if not msg.poll:
            return await interaction.followup.send("❌ Diese Nachricht enthält keine Umfrage.", ephemeral=True)

        poll_obj = msg.poll
        # answers: Liste mit .answer_id und .text / .emoji
        answers = list(poll_obj.answers or [])
        if not answers:
            return await interaction.followup.send("❌ Keine Antworten gefunden.", ephemeral=True)

        # --- Voter je Antwort sammeln ---
        answer_to_voters: Dict[int, List[int]] = {}
        for ans in answers:
            voters = await fetch_answer_voters(self.bot, channel.id, msg.id, ans.answer_id)
            answer_to_voters[ans.answer_id] = voters

        # --- CSV bauen ---
        csv_bytes, filename = self._build_csv(
            question = getattr(poll_obj.question, "text", str(poll_obj.question)),
            answers = [(a.answer_id, a.text if hasattr(a, "text") else str(a)) for a in answers],
            answer_to_voters = answer_to_voters,
            mode = type.value
        )

        file = discord.File(fp=io.BytesIO(csv_bytes), filename=filename)
        title = f"📤 CSV-Export: **{getattr(poll_obj.question, 'text', str(poll_obj.question))}**"
        await interaction.followup.send(content=title, file=file)

    @export_poll.autocomplete("poll")
    async def poll_autocomplete(self, interaction: discord.Interaction, current: str):
        cur = (current or "").lower()
        choices = []

        async def add_choice_from_message(m: discord.Message):
            if getattr(m, "poll", None):
                q = getattr(m.poll.question, "text", str(m.poll.question))
                label = f"{q[:80]}  •  ID:{m.id}"
                if not cur or cur in q.lower() or cur in str(m.id):
                    choices.append(app_commands.Choice(name=label, value=str(m.id)))

        channel = interaction.channel

        # 1) TextChannel
        if isinstance(channel, discord.TextChannel):
            async for m in channel.history(limit=400, oldest_first=False):
                await add_choice_from_message(m)
                if len(choices) >= 25:
                    break

        # 2) Thread
        elif isinstance(channel, discord.Thread):
            async for m in channel.history(limit=400, oldest_first=False):
                await add_choice_from_message(m)
                if len(choices) >= 25:
                    break

        # 3) ForumChannel: Threads (aktiv + archiviert) prüfen
        elif isinstance(channel, discord.ForumChannel):
            threads = list(channel.threads)  # aktuell offene
            # auch archivierte Threads nachladen (nur die letzten N, sonst zu teuer)
            archived = []
            async for th in channel.archived_threads(limit=100, private=False):
                archived.append(th)
                if len(archived) >= 100:
                    break
            for th in (threads + archived)[::-1]:  # neueste zuerst
                try:
                    sm = th.starter_message or await th.fetch_message(th.id)
                except Exception:
                    continue
                await add_choice_from_message(sm)
                if len(choices) >= 25:
                    break

    # 4) Nichts gefunden ➜ kleine Hilfestellung + Fallback für direkte Eingabe
    if not choices:
        # Wenn der User eine ID oder einen Link eingetippt hat, erlauben wir das als direkte Auswahl
        # (Wichtig: Der eigentliche fetch und die Prüfung passieren dann in export_poll)
        typed = current.strip() if current else ""
        if typed:
            # Erlaube Message-ID oder -Link
            choices = [app_commands.Choice(name=f"Direkte Eingabe verwenden: {typed[:90]}", value=typed)]
        else:
            choices = [app_commands.Choice(name="Keine Umfragen gefunden – gib ID/Link ein", value="0")]

    return choices[:25]


    # ---- CSV-Erzeugung ----
    def _build_csv(
        self,
        question: str,
        answers: List[Tuple[int, str]],
        answer_to_voters: Dict[int, List[int]],
        mode: str,
    ) -> Tuple[bytes, str]:
        sep = ";"

        def esc(s: str) -> str:
            return (s or "").replace("\r", " ").replace("\n", " ").strip()

        # Map: user_id -> [answer texts]
        user_choices: Dict[int, List[str]] = {}
        for ans_id, ans_text in answers:
            for uid in answer_to_voters.get(ans_id, []):
                user_choices.setdefault(uid, []).append(ans_text)

        lines: List[str] = []
        if mode == "key":
            # Header
            lines.append("Wahlmöglichkeit;Wähler (Komma getrennt)")
            # Für jede Option: Sammle Voter
            for ans_id, ans_text in answers:
                voters = answer_to_voters.get(ans_id, [])
                voters_mentions = ", ".join(f"<@{uid}>" for uid in voters)
                lines.append(f"{esc(ans_text)}{sep}{esc(voters_mentions)}")
            filename = "poll_export_key_oriented.csv"
        else:
            # Header
            lines.append("Wähler;HatGewählt (Komma getrennt)")
            # Für jeden Wähler: Liste gewählter Antworten
            for uid, picks in user_choices.items():
                picks_str = ", ".join(sorted(picks))
                lines.append(f"<@{uid}>{sep}{esc(picks_str)}")
            filename = "poll_export_value_oriented.csv"

        content = "\n".join(lines) + "\n"
        return content.encode("utf-8"), filename
