## DKS\_Redcogs

This are my Cogs for Redbot. This Cogs will be used for my private Discord and can be used from you too. Please aware that the Cogs are 95% in german!

As you can read from my grammar, you see the reason why :D

![Screenshot: DKS cogs overview](assets/readme-cogs-overview.png)

> 📖 **Full documentation:** [DKS_Redcogs Wiki](https://github.com/Domekologe/DKS_Redcogs/wiki) (English & Deutsch)

## Status Information

| Status | Description |
|---|---|
| Alpha | Alpha Release. Most Commands cannot work |
| Beta | Beta Release. Most Commands should work |
| Info | Not for Production! |
| Release | All Commands should work |
| Stopped | Stopped work on it for different reasons |
| … / On Work | Currently working on it. |

## DKS Web Dashboard (eigenes, modulares Web-Panel)

Neben den AAA3A-kompatiblen Cogs gibt es ein **eigenes** Web-Dashboard. Die Web-App
liegt im separaten Repo **https://github.com/Domekologe/DKS_Redbot_WebApp**; die Bot-Seite
besteht aus diesen Cogs hier:

| Cog | Zweck |
|---|---|
| `webdashboard` | Companion-Cog: RPC-Gateway, Auth, Branding, Custom Pages, Audit-Log. Mit `[p]dksdashboard` verwalten. |
| `webdashboard_stats` | Sammelt Server-Statistiken (Nachrichten/Voice/Status/Einladungen/Aktivität) für die `/stats`-Seite. |
| `dashboardtemplate` | **Kopier-Vorlage** mit allen Feature-Beispielen (Widget, Panels, Liste mit Anlegen/Bearbeiten/Löschen, globales Panel). |
| `dashboardexample` | Minimal-Beispiel der Integration. |

Eigenen Cog anbinden: siehe `webdashboard/INTEGRATION.md` + den Drop-in `dks_dashboard.py`
(1:1 kopierbar, funktioniert auch ohne installiertes Dashboard und parallel zu AAA3A).
Jeder Cog erscheint als **ein Modul mit Tabs** auf der Server-Detailseite.

![Screenshot: DKS Web Dashboard – Cog als Modul mit Tabs](assets/readme-dashboard-module.png)

## About Cogs

| Cog | Status / Version | Description | Commands | Author |
|---|---|---|---|---|
| AdminUtils | Beta 0.2.0 | Commands for Admins and Moderators. | `kick`, `ban`, `timeout`, `purge`, `purgefast`, `messagemove`, `move-memberall`, `move-member`, `copy-channelrole`, `copy-role` | Domekologe |
| eventmessages | Release 0.0.1 | Notifications for join, leave, kick, ban, timeout. | `em-enabled`, `em-channel`, `em-status` | Domekologe |
| GuildTools | Beta 0.1.1 | Some tools for Guilds | `whois`, `setblizzard`, `set-wow-defaults`, `get-absence`, `list-absence`, `add-absence`, `export-userlist`, `export-poll`, `get-readytimes`, `set-readytimes` | Domekologe |
| Misc | Info 0.0.1 | Contains only a ping :D Was my first Cog to test | `ping` | Domekologe |
| neko | Release 0.0.1 | Connects to Nekos.best API | `neko`, `neko-cat` | Domekologe |
| nekoapi | Release 0.0.1 | Connects to Nekosapi.com (incl. NSFW ratings) | `nekoapi`, `nekoapi-rating` | Domekologe |
| reactionrole | Release 0.0.1 | Feature-rich Reaction Roles cog with Dashboard support. | `reactionrole-set`, `reactionrole-remove`, `reactionrole-get`, `reactionrole-sync` | Domekologe |
| adminprotocol | Release 0.0.1 | Detailed admin & activity logging into configurable channels (fully web-configured). | *Listeners only (no commands)* | Domekologe |
| channeljoinnotification | Release 0.0.1 | DMs users with a customizable text when they join configured voice channels. | `/join-notification` | Domekologe |
| warcraftlogs_classic | Beta 0.2.2 | Information from Warcraftlogs Classic (commands suffixed `-classic`). Shares the global **Warcraft Logs API** key panel with the retail cog. | `warcraftlogs-classic` (alias `wcl-classic`: `gear`/`rank`), `wclset-classic` | aikaterna (Original) / Domekologe |
| warcraftlogs_retail | Beta 0.1.0 | Information from Warcraftlogs Retail (current retail raid zones fetched dynamically; commands suffixed `-retail`). Shares the global **Warcraft Logs API** key panel with the classic cog. | `warcraftlogs-retail` (alias `wcl-retail`: `gear`/`rank`), `wclset-retail` | Domekologe |
| WoWTools | Beta 0.1.2 | WoW **Retail** tools: ingame stats, information, etc. from WoW characters. Slash commands prefixed `wowt-`; `region` is a dropdown (eu/us/kr/tw). | `wowt-charinfo`, `wowt-charstats`, `wowt-comparechars`, `wowt-cvar`, `wowt-gearcheck`, `wowt-gmanage`, `wowt-gmset`, `wowt-raiderio`, `wowt-raidinfo`, `wowt-rating`, `wowt-sbset`, `wowt-serverset`, `wowt-talentcheck`, `wowt-wowscoreboard`, `wowt-wowtoken` | Karlo (Original) / Domekologe |
| wowtools_classic | Beta 0.1.0 | WoW **Classic** tools: same commands as WoWTools, slash prefixed `wowtc-`. Shares WoWTools' settings (region/realm/API). | `wowtc-charinfo`, `wowtc-charstats`, `wowtc-comparechars`, `wowtc-cvar`, `wowtc-gearcheck`, `wowtc-gmanage`, `wowtc-gmset`, `wowtc-raiderio`, `wowtc-raidinfo`, `wowtc-rating`, `wowtc-sbset`, `wowtc-serverset`, `wowtc-talentcheck`, `wowtc-wowscoreboard`, `wowtc-wowtoken` | Karlo (Original) / Domekologe |
| wowguild_automation | Info / On Work | WoW Guild automation for new members/guests. | `/wow-user`, `/wow-admin`, `/wow-masteradmin` | Domekologe |
| webdashboard | Release 1.0.0 | Companion cog: RPC gateway, auth, branding, custom pages, audit log + the cog-integration framework. | `dksdashboard` (status/start/stop/bind/token/regen) | Domekologe |
| webdashboard_stats | Release 1.0.0 | Collects server statistics (messages/voice/status/invites/activity, heatmaps, peaks) for the dashboard `/stats` page. | *Listeners only (no commands)* | Domekologe |
| dashboardtemplate | Template | Annotated reference cog for the DKS dashboard integration (incl. the `L`/`tr`/`tr_lang` i18n helpers). | `dashboardtemplate` | Domekologe |
| dashboardexample | Example | Minimal example of dashboard integration (widget + panel). | `dashboardexample` | Domekologe |

> Most cogs support **German & English**: dashboard module texts follow the website language toggle, and each cog has a per-server **language** setting (in its dashboard module) for its Discord output.

## 🌐 Web Dashboard Integration

Several cogs in this repository feature **native integration with AAA3A's Red-Web-Dashboard**! 
Instead of configuring everything strictly via Discord commands, you can manage them seamlessly through your browser:

- **AdminUtils** (Templates & Settings)
- **eventmessages** (Channel routing & Custom Event Texts)
- **reactionrole** (Easily add and map reaction roles visually)
- **WoWTools** (Guild-profile setup & API config)
- **wowguild_automation** (Full Dashboard based role & channel mapping setup)

**Modern UI Details:** 
These dashboard pages have been styled with a custom, premium *glassmorphism* aesthetic that provides a highly modern, sleek experience while remaining 100% compatible with the AAA3A Argon Dashboard native layout!

I am Using the Original Dashboard from AAA3A with some customizations for me