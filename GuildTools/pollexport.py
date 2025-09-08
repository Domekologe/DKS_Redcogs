# guildtools/pollexport.py
import io
import re
from typing import Dict, List, Tuple, Optional

import discord
from discord import app_commands
from redbot.core import commands


# ---- kleine Helper: REST-Call für Voter holen (paged) ----
async def fetch_answer_voters(
    client: discord.Client, channel_id: int, message_id: int, answer_id: int, limit: int = 1000
) -> List[int]:
    user_ids: List[int] = []
    after: Optional[int] = None
    fetched = 0

    while True:
        try:
            data = await client.http.get_poll_answer_voters(
                channel_id, message_id, answer_id, limit=min(100, limit - fetched), after=after
            )
        except AttributeError:
            route = discord.http.Route(
                "GET",
                "/channels/{channel_id}/polls/{message_id}/answers/{answer_id}/voters",
                channel_id=channel_id,
                message_id=message_id,
                answer_id=answer_id,
            )
            params = {"limit": min(100, limit - fetched)}
            if after:
                params["after"] = after
            data = await client.http.request(route, params=params)

        users = data.get("users", []) if isinstance(data, dict) else data
        if not users:
            break

        ids = []
        for u in users:
            uid = int(u["id"] if isinstance(u, dict) else int(u))
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

    # ---------- Helper innerhalb der Klasse ----------
    def _ans_id(self, ans) -> int:
        # verschiedene discord.py-Versionen: mal .id, mal .answer_id
        val = getattr(ans, "answer_id", None)
        if val is None:
            val = getattr(ans, "id", None)
        if val is None:
            raise AttributeError("PollAnswer hat weder 'answer_id' noch 'id'.")
        return int(val)

    def _ans_text(self, ans) -> str:
        # bevorzugt Klartext; sonst evtl. über poll_media; sonst str(ans)
        txt = getattr(ans, "text", None)
        if not txt:
            pm = getattr(ans, "poll_media", None)
            txt = getattr(pm, "text", None) if pm else None
        return txt if txt else str(ans)

    @staticmethod
    def parse_message_ref(text: str, fallback_channel_id: int) -> Tuple[int, int]:
        """Parst Nachricht-ID oder -Link. Gibt (channel_id, message_id) zurück."""
        m = re.search(r"/channels/\d+/(\d+)/(\d+)", text or "")
        if m:
            return int(m.group(1)), int(m.group(2))
        return fallback_channel_id, int(text)

    # ---------- Slash-Command ----------
    @app_commands.describe(
        poll="Wähle die Umfrage (Autocomplete: letzte Polls im Channel, alternativ ID/Link einfügen)",
        mode="Export-Ansicht",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Key-Oriented", value="key"),
            app_commands.Choice(name="Value-Oriented", value="value"),
        ]
    )
    @app_commands.command(
        name="export-poll", description="Exportiert eine native Discord-Umfrage als CSV (;-getrennt)."
    )
    async def export_poll(self, interaction: discord.Interaction, poll: str, mode: app_commands.Choice[str]):
        await interaction.response.defer(thinking=True)

        # ID oder Link parsen
        try:
            chan_id, message_id = self.parse_message_ref(poll, interaction.channel.id)
        except Exception:
            return await interaction.followup.send("❌ Ungültige Umfrage-Auswahl.", ephemeral=True)

        # Channel holen (kann ein anderer Channel/Thread sein)
        ch = interaction.guild.get_channel(chan_id)
        if ch is None:
            try:
                ch = await interaction.client.fetch_channel(chan_id)
            except Exception:
                return await interaction.followup.send("❌ Ziel-Channel nicht gefunden/zugreifbar.", ephemeral=True)

        if not isinstance(ch, (discord.TextChannel, discord.Thread, discord.ForumChannel)):
            return await interaction.followup.send("❌ Dieser Befehl funktioniert nur in Textchannels/Threads.", ephemeral=True)

        # Nachricht laden
        try:
            msg = await ch.fetch_message(message_id)
        except discord.NotFound:
            return await interaction.followup.send("❌ Nachricht nicht gefunden.", ephemeral=True)
        except discord.Forbidden:
            return await interaction.followup.send("❌ Keine Berechtigung, die Nachricht zu lesen.", ephemeral=True)

        if not getattr(msg, "poll", None):
            return await interaction.followup.send("❌ Diese Nachricht enthält keine Umfrage.", ephemeral=True)

        poll_obj = msg.poll
        answers = list(poll_obj.answers or [])
        if not answers:
            return await interaction.followup.send("❌ Keine Antworten gefunden.", ephemeral=True)

        # --- Voter je Antwort sammeln ---
        answer_to_voters: Dict[int, List[int]] = {}
        for ans in answers:
            ans_id = self._ans_id(ans)
            voters = await fetch_answer_voters(self.bot, msg.channel.id, msg.id, ans_id)
            answer_to_voters[ans_id] = voters

        # --- CSV bauen ---
        question_text = getattr(poll_obj.question, "text", str(poll_obj.question))
        answers_list: List[Tuple[int, str]] = [(self._ans_id(a), self._ans_text(a)) for a in answers]

        csv_bytes, filename = self._build_csv(
            question=question_text,
            answers=answers_list,
            answer_to_voters=answer_to_voters,
            mode=mode.value,
        )

        file = discord.File(fp=io.BytesIO(csv_bytes), filename=filename)
        title = f"📤 CSV-Export: **{question_text}**"
        await interaction.followup.send(content=title, file=file)

    @export_poll.autocomplete("poll")
    async def poll_autocomplete(self, interaction: discord.Interaction, current: str):
        def safe_label(q: str, mid: int) -> str:
            q = (q or "").replace("\n", " ").replace("\r", " ").strip()
            if not q:
                q = f"Umfrage {mid}"
            label = f"{q}  •  ID:{mid}"
            return label[:100]

        cur = (current or "").lower()
        channel = interaction.channel
        choices: List[app_commands.Choice[str]] = []
        seen_ids = set()

        async def try_add_from_message(m: discord.Message):
            if getattr(m, "poll", None) and m.id not in seen_ids:
                q = getattr(m.poll.question, "text", str(m.poll.question))
                label = safe_label(q, m.id)
                if (not cur) or (cur in (q or "").lower()) or (cur in str(m.id)):
                    choices.append(app_commands.Choice(name=label, value=str(m.id)))
                    seen_ids.add(m.id)

        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            async for m in channel.history(limit=400, oldest_first=False):
                await try_add_from_message(m)
                if len(choices) >= 25:
                    break
        elif isinstance(channel, discord.ForumChannel):
            threads = list(channel.threads)
            async for th in channel.archived_threads(limit=100, private=False):
                threads.append(th)
            for th in sorted(threads, key=lambda t: t.id, reverse=True):
                try:
                    sm = th.starter_message or await th.fetch_message(th.id)
                except Exception:
                    continue
                await try_add_from_message(sm)
                if len(choices) >= 25:
                    break

        if not choices:
            typed = (current or "").strip()
            if typed:
                choices = [app_commands.Choice(name=f"Direkte Eingabe verwenden: {typed[:100]}", value=typed)]
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
            lines.append("Wahlmöglichkeit;Wähler (Komma getrennt)")
            for _, ans_text in answers:
                voters = [uid for uid in answer_to_voters.get(self._find_answer_id(answers, ans_text), [])]
                voters_mentions = ", ".join(f"<@{uid}>" for uid in voters)
                lines.append(f"{esc(ans_text)}{sep}{esc(voters_mentions)}")
            filename = "poll_export_key_oriented.csv"
        else:
            lines.append("Wähler;HatGewählt (Komma getrennt)")
            for uid, picks in user_choices.items():
                picks_str = ", ".join(sorted(picks))
                lines.append(f"<@{uid}>{sep}{esc(picks_str)}")
            filename = "poll_export_value_oriented.csv"

        content = "\n".join(lines) + "\n"
        return content.encode("utf-8"), filename

    def _find_answer_id(self, answers: List[Tuple[int, str]], text: str) -> int:
        for aid, t in answers:
            if t == text:
                return aid
        return -1
