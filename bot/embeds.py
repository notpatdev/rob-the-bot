from __future__ import annotations

from datetime import datetime

import discord

from bot import messages
from bot.config import BotConfig
from bot.database import DommeProfile, LeaderboardRow, SubProfile, ThroneSend, VerificationRequest
from bot.utils import detect_platform, mention_channel, user_mention

PURPLE = discord.Color.from_rgb(181, 101, 255)
PINK = discord.Color.from_rgb(255, 101, 178)
GREEN = discord.Color.from_rgb(59, 201, 122)
RED = discord.Color.from_rgb(235, 87, 87)
ORANGE = discord.Color.from_rgb(245, 145, 61)
SOFT_DARK = discord.Color.from_rgb(42, 37, 58)

# Preset profile colors available to dommes during setup (value, emoji, label)
PROFILE_COLOR_PRESETS: list[tuple[int, str, str]] = [
    (PINK.value,                               "💗", "Pink"),
    (PURPLE.value,                             "💜", "Purple"),
    (discord.Color.from_rgb(235, 87, 87).value, "🔴", "Red"),
    (discord.Color.from_rgb(70, 130, 180).value, "🔵", "Blue"),
    (GREEN.value,                              "💚", "Green"),
    (discord.Color.from_rgb(255, 215, 0).value, "🟡", "Gold"),
    (discord.Color.from_rgb(0, 188, 188).value, "🩵", "Teal"),
    (SOFT_DARK.value,                          "🖤", "Dark"),
]


def _butler_footer(detail: str) -> str:
    """Return footer text in the standard Butler format (for use with TextDisplay)."""
    return f"-# The Butler • {detail}"


def _styled_container(
    *,
    title: str,
    description: str | None = None,
    color: discord.Color,
    footer: str | None = None,
) -> discord.ui.Container:
    """Create a styled Container with title, optional description, and optional footer."""
    items: list[discord.ui.TextDisplay] = []
    if description:
        items.append(discord.ui.TextDisplay(f"## {title}\n{description}"))
    else:
        items.append(discord.ui.TextDisplay(f"## {title}"))
    if footer:
        items.append(discord.ui.TextDisplay(footer))
    return discord.ui.Container(*items, accent_color=color)


def _styled_container_with_thumbnail(
    *,
    title: str,
    description: str | None = None,
    color: discord.Color,
    thumbnail_url: str,
    footer: str | None = None,
) -> discord.ui.Container:
    """Create a styled Container with a Section containing a thumbnail accessory."""
    text = f"## {title}"
    if description:
        text += f"\n{description}"
    section = discord.ui.Section(
        discord.ui.TextDisplay(text),
        accessory=discord.ui.Thumbnail(thumbnail_url),
    )
    items: list[discord.ui.Section | discord.ui.TextDisplay] = [section]
    if footer:
        items.append(discord.ui.TextDisplay(footer))
    return discord.ui.Container(*items, accent_color=color)


def _profile_value(value: str | None) -> str:
    return value.strip() if value and value.strip() else "Not provided"


def _feature_value(enabled: bool) -> str:
    return "Yes" if enabled else "No"


def _add_chunked_text_displays(
    items: list[discord.ui.TextDisplay],
    *,
    name: str,
    lines: list[str],
) -> None:
    """Splits long text into multiple TextDisplays, each max 1024 chars."""
    chunks: list[str] = []
    current_lines: list[str] = []
    current_length = 0

    for line in lines:
        line_length = len(line)
        projected_length = line_length if not current_lines else current_length + 1 + line_length
        if current_lines and projected_length > 1024:
            chunks.append("\n".join(current_lines))
            current_lines = [line]
            current_length = line_length
            continue

        current_lines.append(line)
        current_length = projected_length

    if current_lines:
        chunks.append("\n".join(current_lines))

    for index, chunk in enumerate(chunks):
        heading = name if index == 0 else f"{name} (cont.)"
        items.append(discord.ui.TextDisplay(f"**{heading}**\n{chunk}"))


def _smart_link_line(url: str | None) -> str | None:
    """Return 'Label: URL' if url is set, otherwise None."""
    if not url or not url.strip():
        return None
    label = detect_platform(url.strip())
    return f"**{label}:** {url.strip()}"


def _has_value(value: str | None) -> bool:
    return bool(value and value.strip())


def welcome_container(member: discord.Member) -> discord.ui.Container:
    text = f"## {messages.WELCOME_TITLE}\n{messages.WELCOME_DESCRIPTION.format(user_mention=member.mention)}"
    section = discord.ui.Section(
        discord.ui.TextDisplay(text),
        accessory=discord.ui.Thumbnail(member.display_avatar.url),
    )
    footer = discord.ui.TextDisplay(_butler_footer("18+ verification required"))
    return discord.ui.Container(section, footer, accent_color=PINK)


def verification_panel_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.VERIFICATION_PANEL_TITLE,
        description=messages.VERIFICATION_PANEL_DESCRIPTION,
        color=PURPLE,
        footer=_butler_footer("Age verification"),
    )


def initial_verification_dm_container(notice: str | None = None) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.INITIAL_VERIFICATION_DM_TITLE}\n"
            f"{messages.INITIAL_VERIFICATION_DM_DESCRIPTION}"
        ),
    ]
    if notice:
        items.append(discord.ui.TextDisplay(f"**Invalid Submission**\n{notice}"))
    items.append(discord.ui.TextDisplay(_butler_footer("Verification expires in 5 minutes")))
    return discord.ui.Container(*items, accent_color=PURPLE)


def role_prompt_container(selected_role: str | None = None) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.ROLE_PROMPT_TITLE}\n{messages.ROLE_PROMPT_DESCRIPTION}"
        ),
    ]
    if selected_role:
        items.append(discord.ui.TextDisplay(f"**Selected Role**\n{selected_role}"))
    items.append(discord.ui.TextDisplay(_butler_footer("Role selection")))
    return discord.ui.Container(*items, accent_color=PINK)


def pending_review_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.PENDING_REVIEW_TITLE,
        description=messages.PENDING_REVIEW_DESCRIPTION,
        color=PURPLE,
        footer=_butler_footer("Staff review pending"),
    )


def approved_dm_container(config: BotConfig) -> discord.ui.Container:
    return _styled_container(
        title=messages.APPROVED_DM_TITLE,
        description=messages.APPROVED_DM_DESCRIPTION.format(
            roles_channel=mention_channel(config.roles_channel_id),
            introductions_channel=mention_channel(config.introductions_channel_id),
            general_channel=mention_channel(config.general_channel_id),
        ),
        color=GREEN,
        footer=_butler_footer("Welcome to The Drain Gang"),
    )


def denied_underage_dm_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.DENIED_UNDERAGE_DM_TITLE,
        description=messages.DENIED_UNDERAGE_DM_DESCRIPTION,
        color=RED,
        footer=_butler_footer("Verification denied"),
    )


def denied_invalid_dm_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.DENIED_INVALID_DM_TITLE,
        description=messages.DENIED_INVALID_DM_DESCRIPTION,
        color=ORANGE,
        footer=_butler_footer("Verification denied"),
    )


def session_expired_dm_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.SESSION_EXPIRED_DM_TITLE,
        description=messages.SESSION_EXPIRED_DM_DESCRIPTION,
        color=SOFT_DARK,
        footer=_butler_footer("Verification expired"),
    )


def invalid_submission_dm_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.INVALID_SUBMISSION_DM_TITLE,
        description=messages.INVALID_SUBMISSION_DM_DESCRIPTION,
        color=ORANGE,
        footer=_butler_footer("Try again"),
    )


def verification_log_container(
    request: VerificationRequest,
    member: discord.Member | None,
) -> discord.ui.Container:
    nickname_or_username = member.display_name if member else request.username
    verification_value = request.verification_value or "Not provided"
    verification_display = verification_value
    if request.verification_type == "Photo":
        verification_display = "Photo submitted below."

    description = (
        f"**User:** {user_mention(request.user_id)} ({nickname_or_username})\n\n"
        f"**Verification Type:** {request.verification_type or 'Unknown'}\n\n"
        f"**Verification:**\n{verification_display}\n\n"
        f"**User has marked they are a {request.selected_role or 'Unknown'}**"
    )

    items: list[discord.ui.Section | discord.ui.TextDisplay | discord.ui.MediaGallery] = []
    text = f"## New Age Verification Request\n{description}"
    if member:
        section = discord.ui.Section(
            discord.ui.TextDisplay(text),
            accessory=discord.ui.Thumbnail(member.display_avatar.url),
        )
        items.append(section)
    else:
        items.append(discord.ui.TextDisplay(text))

    if request.verification_type == "Photo" and request.verification_value:
        items.append(discord.ui.MediaGallery(
            discord.ui.MediaGalleryItem(request.verification_value)
        ))

    items.append(discord.ui.TextDisplay(_butler_footer(f"Request ID #{request.id}")))
    return discord.ui.Container(*items, accent_color=PURPLE)


def verification_outcome_container(
    *,
    request: VerificationRequest,
    moderator: discord.Member | discord.User,
    title: str,
    color: discord.Color,
    status: str,
) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(f"## {title}"),
        discord.ui.TextDisplay(f"**User**\n{user_mention(request.user_id)} ({request.username})"),
        discord.ui.TextDisplay(f"**Selected Role**\n{request.selected_role or 'Unknown'}"),
        discord.ui.TextDisplay(f"**Verification Date**\n{discord.utils.utcnow().strftime('%m/%d/%Y')}"),
        discord.ui.TextDisplay(f"**Mod Responsible for Verification**\n{moderator.name} ({moderator.mention})"),
        discord.ui.TextDisplay(f"**Verification method**\n{request.verification_type or 'Unknown'}"),
        discord.ui.TextDisplay(f"**Status**\n{status}"),
        discord.ui.TextDisplay(_butler_footer(f"Request ID #{request.id}")),
    ]
    return discord.ui.Container(*items, accent_color=color)


def verification_status_container(
    request: VerificationRequest | None,
    user: discord.User | discord.Member,
) -> discord.ui.Container:
    items: list[discord.ui.Section | discord.ui.TextDisplay] = []

    text = f"## Verification Status\n**User:** {user.mention} ({user.name})"
    section = discord.ui.Section(
        discord.ui.TextDisplay(text),
        accessory=discord.ui.Thumbnail(user.display_avatar.url),
    )
    items.append(section)

    if request is None:
        items.append(discord.ui.TextDisplay("No verification record was found for this user."))
    else:
        items.append(discord.ui.TextDisplay(f"**Status:** {request.status}"))
        items.append(discord.ui.TextDisplay(f"**Selected Role:** {request.selected_role or 'Not selected'}"))
        items.append(discord.ui.TextDisplay(f"**Verification method:** {request.verification_type or 'Not submitted'}"))
        items.append(discord.ui.TextDisplay(f"**Submitted:** {request.submitted_at}"))
        if request.reviewed_at:
            items.append(discord.ui.TextDisplay(f"**Reviewed:** {request.reviewed_at}"))

    items.append(discord.ui.TextDisplay(_butler_footer("Staff only")))
    return discord.ui.Container(*items, accent_color=PURPLE)


def verification_cleanup_container(
    *,
    role: discord.Role,
    members: list[discord.Member],
) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(f"## Unverified Cleanup\nUsers who still have {role.mention}: **{len(members)}**"),
    ]
    if members:
        visible_members = members[:25]
        lines = [f"• {member.mention} ({member.display_name})" for member in visible_members]
        if len(members) > len(visible_members):
            lines.append(f"• +{len(members) - len(visible_members)} more")
        items.append(discord.ui.TextDisplay(f"**Members**\n" + "\n".join(lines)))
    else:
        items.append(discord.ui.TextDisplay("**Members**\nNo users currently have this role."))

    items.append(discord.ui.TextDisplay(_butler_footer("Staff only")))
    return discord.ui.Container(*items, accent_color=PURPLE)


def build_help_pages(
    *,
    is_domme: bool,
    is_sub: bool,
    is_moderator: bool,
) -> list[tuple[str, int, str, tuple[tuple[str, str], ...]]]:
    """Return the help pages relevant to a member's roles.

    Each page is ``(section, color, blurb, entries)``. The "General" page is
    always included. Mods see Verification / Moderation / System. Dommes see
    the Domme Profiles page. Subs see the Sub Profiles page. Members with no
    matching role only see General.
    """
    general_page = (
        "General",
        PINK,
        "Everyone can use these commands.",
        (
            ("/help", "Shows this help menu, tailored to your roles."),
        ),
    )
    domme_page = (
        "Domme Profiles",
        PINK,
        "Domme profile setup and management.",
        (
            ("/domme", "Shows your Domme profile publicly, or starts setup if you don't have one. Works in DMs too."),
            ("/domme user:@Someone", "Shows another member's Domme profile publicly."),
            ("/domme action:leaderboard", "Shows your Throne send leaderboard publicly."),
            ("/domme action:delete", "Deletes your saved Domme profile after confirmation."),
        ),
    )
    sub_page = (
        "Sub Profiles",
        SOFT_DARK,
        "Sub profile setup for Throne leaderboard tracking.",
        (
            ("/sub", "Link your Throne sending name to your Discord for automatic send tracking."),
            ("/sub action:delete", "Deletes your saved sub profile."),
        ),
    )
    verification_page = (
        "Verification",
        PINK,
        "Verification commands and panel setup.",
        (
            ("!setup_verification", "Posts the verification panel in the configured verification channel."),
            ("!verify_status <user>", "Checks a user's verification status."),
        ),
    )
    moderation_page = (
        "Moderation",
        PURPLE,
        "Moderation tools for the verification queue and Throne tracker.",
        (
            ("!verify_cleanup", "Shows users who still have the Unverified role."),
            ("/throne_refresh", "Force an immediate Throne poll, optionally for a single Domme."),
            ("/reaction_role_setup", "Open a setup form to create a reaction-role embed and mappings."),
        ),
    )
    system_page = (
        "System",
        SOFT_DARK,
        "Restricted system controls and reference tools.",
        (
            ("/help", "Shows this help menu."),
            ("!import ids", "Upload a JSON or text file with your server IDs - bot parses and confirms before saving."),
            ("!resync [guild|clear|global]", "Developer/admin command to re-sync slash commands."),
        ),
    )

    pages: list[tuple[str, int, str, tuple[tuple[str, str], ...]]] = [general_page]
    if is_domme:
        pages.append(domme_page)
    if is_sub:
        pages.append(sub_page)
    if is_moderator:
        pages.extend([verification_page, moderation_page, system_page])
    return pages


def help_page_container(
    page_index: int,
    total_pages: int,
    pages: list[tuple[str, int, str, tuple[tuple[str, str], ...]]] | None = None,
) -> discord.ui.Container:
    if pages is None:
        # Fallback: show a generic page list when called without a roles context.
        pages = build_help_pages(is_domme=True, is_sub=True, is_moderator=True)
    # Clamp the page index defensively in case the caller passes a stale value.
    page_index = max(0, min(page_index, len(pages) - 1))
    section, color, blurb, entries = pages[page_index]

    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(f"## The Butler Help • {section}\n{blurb}"),
    ]
    for name, description in entries:
        items.append(discord.ui.TextDisplay(f"**{name}**\n{description}"))
    items.append(discord.ui.TextDisplay(_butler_footer(f"Help page {page_index + 1}/{total_pages}")))
    return discord.ui.Container(*items, accent_color=color)


def reaction_role_embed(
    *,
    title: str,
    description: str,
    color: discord.Color,
    mappings: list[tuple[str, str]],
    creator: discord.abc.User,
) -> discord.Embed:
    """Reaction role embed - kept as Embed since it's posted publicly and receives reactions."""
    embed = discord.Embed(
        title=title.strip() or "Reaction Roles",
        description=description.strip(),
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    lines = [f"{emoji} = {role_mention}" for emoji, role_mention in mappings]
    embed.add_field(name="Role Reactions", value="\n".join(lines), inline=False)
    embed.set_footer(text=f"The Butler • Reaction roles • Setup by {creator.name}")
    return embed


def reaction_role_created_container(
    jump_url: str,
    channel: discord.TextChannel,
    mappings: list[tuple[str, str, discord.Role]],
) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay("## Reaction-role message created"),
        discord.ui.TextDisplay(f"**Channel:** {channel.mention}"),
        discord.ui.TextDisplay(f"**Mappings:** {len(mappings)}"),
        discord.ui.TextDisplay(f"**Message:** [Jump to message]({jump_url})"),
        discord.ui.TextDisplay(_butler_footer("Reaction roles ready")),
    ]
    return discord.ui.Container(*items, accent_color=GREEN)


def import_ids_container() -> discord.ui.Container:
    """Prompt container for the !import ids command — button rendered below by the view."""
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            "## 📥 Import Server IDs\n"
            "Click **Upload File** below to import your server's channel and role IDs.\n\n"
            "Upload a **JSON** or **text** file containing your IDs — the bot will "
            "parse it and ask you to confirm before saving anything."
        ),
        discord.ui.TextDisplay(
            "**Accepted formats**\n"
            "`JSON` — `{\"GUILD_ID\": 123, \"DOMME_ROLE_ID\": 456, ...}`\n"
            "`Text` — `GUILD_ID=123` or `guild_id: 123` (one per line)"
        ),
        discord.ui.TextDisplay(_butler_footer("Admin only • channels.py will be updated on confirm")),
    ]
    return discord.ui.Container(*items, accent_color=PURPLE)


def import_ids_confirm_container(parsed: dict[str, int], warnings: list[str]) -> discord.ui.Container:
    """Shows the IDs the bot parsed so the admin can confirm or cancel."""
    field_labels = {
        "GUILD_ID": "Guild",
        "REGISTRATION_CHANNEL_ID": "Registration Channel",
        "LEADERBOARD_CHANNEL_ID": "Leaderboard Channel",
        "SEND_TRACK_CHANNEL_ID": "Send Track Channel",
        "DOMME_ROLE_ID": "Domme Role",
        "SUBMISSIVE_ROLE_ID": "Submissive Role",
        "MODERATION_ROLE_ID": "Moderation Role",
        "EVENT_BAN_ROLE_ID": "Event Ban Role",
    }
    lines = [f"**{field_labels.get(k, k)}:** `{v}`" for k, v in parsed.items()]
    desc = "\n".join(lines)
    if warnings:
        desc += "\n\n⚠️ **Warnings:**\n" + "\n".join(f"• {w}" for w in warnings)

    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(f"## ✅ Confirm ID Import\n{desc}"),
        discord.ui.TextDisplay(_butler_footer("React to confirm or cancel")),
    ]
    return discord.ui.Container(*items, accent_color=GREEN)


def domme_setup_intro_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.DOMME_SETUP_INTRO_TITLE,
        description=messages.DOMME_SETUP_INTRO_DESCRIPTION,
        color=PINK,
        footer=_butler_footer("Domme profile setup"),
    )


def domme_setup_name_container(*, name: str | None, honorific: str | None) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.DOMME_SETUP_NAME_TITLE}\n{messages.DOMME_SETUP_NAME_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Name**\n{_profile_value(name)}"),
        discord.ui.TextDisplay(f"**Honorific**\n{_profile_value(honorific)}"),
        discord.ui.TextDisplay(_butler_footer("Step 1/4")),
    ]
    return discord.ui.Container(*items, accent_color=PINK)


def domme_setup_details_container(
    *,
    pronouns: str | None,
    age: str | None,
    tribute_price: str | None,
    kinks: str | None,
    limits: str | None,
) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.DOMME_SETUP_DETAILS_TITLE}\n{messages.DOMME_SETUP_DETAILS_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Pronouns**\n{_profile_value(pronouns)}"),
        discord.ui.TextDisplay(f"**Age:** {_profile_value(age)} | **Tribute Fee Price:** {_profile_value(tribute_price)}"),
        discord.ui.TextDisplay(f"**Kinks**\n{_profile_value(kinks)}"),
        discord.ui.TextDisplay(f"**Limits**\n{_profile_value(limits)}"),
        discord.ui.TextDisplay(_butler_footer("Step 2/4")),
    ]
    return discord.ui.Container(*items, accent_color=PURPLE)


def domme_setup_links_container(
    *,
    throne: str | None,
    tribute_link: str | None,
    payment_link1: str | None,
    payment_link2: str | None,
    payment_link3: str | None,
    payment_link4: str | None,
    content_link1: str | None,
    content_link2: str | None,
    content_link3: str | None,
    content_link4: str | None,
) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.DOMME_SETUP_PAYMENTS_TITLE}\n{messages.DOMME_SETUP_PAYMENTS_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Throne**\n{_profile_value(throne)}"),
        discord.ui.TextDisplay(f"**Tribute Link**\n{_profile_value(tribute_link)}"),
    ]
    # Payment links — show smart-detected labels
    pay_lines = [
        line for link in (payment_link1, payment_link2, payment_link3, payment_link4)
        if (line := _smart_link_line(link))
    ]
    items.append(discord.ui.TextDisplay(
        f"**Payment Links**\n{chr(10).join(pay_lines) if pay_lines else 'Not provided'}"
    ))
    # Content links — smart-detected labels
    content_lines = [
        line for link in (content_link1, content_link2, content_link3, content_link4)
        if (line := _smart_link_line(link))
    ]
    items.append(discord.ui.TextDisplay(
        f"**Content Links**\n{chr(10).join(content_lines) if content_lines else 'Not provided'}"
    ))
    items.append(discord.ui.TextDisplay(_butler_footer("Step 3/4")))
    return discord.ui.Container(*items, accent_color=PURPLE)


def domme_setup_throne_container(*, throne: str | None) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.DOMME_SETUP_THRONE_TITLE}\n{messages.DOMME_SETUP_THRONE_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Throne**\n{_profile_value(throne)}"),
        discord.ui.TextDisplay(_butler_footer("Throne tracking (optional)")),
    ]
    return discord.ui.Container(*items, accent_color=PINK)


def domme_setup_color_container(*, profile_color: int) -> discord.ui.Container:
    color = discord.Color(profile_color)
    # Find the matching preset label if any
    label = next(
        (lbl for val, _emoji, lbl in PROFILE_COLOR_PRESETS if val == profile_color),
        f"Custom (#{profile_color:06X})",
    )
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.DOMME_SETUP_COLOR_TITLE}\n{messages.DOMME_SETUP_COLOR_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Selected Color**\n{label}"),
        discord.ui.TextDisplay(_butler_footer("Step 4/4")),
    ]
    return discord.ui.Container(*items, accent_color=color)


def domme_setup_review_container(
    *,
    name: str | None,
    honorific: str | None,
    pronouns: str | None,
    age: str | None,
    tribute_price: str | None,
    throne: str | None,
    tribute_link: str | None,
    payment_link1: str | None,
    payment_link2: str | None,
    payment_link3: str | None,
    payment_link4: str | None,
    content_link1: str | None,
    content_link2: str | None,
    content_link3: str | None,
    content_link4: str | None,
    profile_color: int,
    throne_tracking_enabled: bool,
    kinks: str | None,
    limits: str | None,
) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.DOMME_SETUP_REVIEW_TITLE}\n{messages.DOMME_SETUP_REVIEW_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(
            f"**Identity**\n"
            f"**Name:** {_profile_value(name)}\n"
            f"**Honorific:** {_profile_value(honorific)}\n"
            f"**Pronouns:** {_profile_value(pronouns)}"
        ),
        discord.ui.TextDisplay(
            f"**Details**\n"
            f"**Age:** {_profile_value(age)}\n"
            f"**Tribute Fee Price:** {_profile_value(tribute_price)}"
        ),
    ]
    if _has_value(kinks):
        items.append(discord.ui.TextDisplay(f"**Kinks**\n{kinks}"))
    if _has_value(limits):
        items.append(discord.ui.TextDisplay(f"**Limits**\n{limits}"))
    # Throne + tribute
    items.append(discord.ui.TextDisplay(
        f"**Throne:** {_profile_value(throne)} | **Tribute Link:** {_profile_value(tribute_link)}"
    ))
    # Payment links
    pay_lines = [
        line for link in (payment_link1, payment_link2, payment_link3, payment_link4)
        if (line := _smart_link_line(link))
    ]
    items.append(discord.ui.TextDisplay(
        f"**Payment Links**\n{chr(10).join(pay_lines) if pay_lines else 'None'}"
    ))
    # Content links
    content_lines = [
        line for link in (content_link1, content_link2, content_link3, content_link4)
        if (line := _smart_link_line(link))
    ]
    items.append(discord.ui.TextDisplay(
        f"**Content Links**\n{chr(10).join(content_lines) if content_lines else 'None'}"
    ))
    color_label = next(
        (lbl for val, _emoji, lbl in PROFILE_COLOR_PRESETS if val == profile_color),
        f"#{profile_color:06X}",
    )
    items.append(discord.ui.TextDisplay(
        f"**Throne Tracking:** {_feature_value(throne_tracking_enabled)} | **Profile Color:** {color_label}"
    ))
    items.append(discord.ui.TextDisplay(_butler_footer("Ready to save")))
    return discord.ui.Container(*items, accent_color=discord.Color(profile_color))


def domme_setup_complete_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.DOMME_SETUP_COMPLETE_TITLE,
        description=messages.DOMME_SETUP_COMPLETE_DESCRIPTION,
        color=GREEN,
        footer=_butler_footer("Profile saved"),
    )


def domme_setup_later_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.DOMME_SETUP_LATER_TITLE,
        description=messages.DOMME_SETUP_LATER_DESCRIPTION,
        color=SOFT_DARK,
        footer=_butler_footer("Setup paused"),
    )


def domme_setup_cancelled_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.DOMME_SETUP_CANCELLED_TITLE,
        description=messages.DOMME_SETUP_CANCELLED_DESCRIPTION,
        color=SOFT_DARK,
        footer=_butler_footer("Setup cancelled"),
    )


def domme_profile_container(
    profile: DommeProfile,
    member: discord.Member | discord.User,
    *,
    is_verified: bool = False,
) -> discord.ui.Container:
    display_name = member.display_name if isinstance(member, discord.Member) else member.name

    # Build a clean description block
    desc_parts: list[str] = []
    if _has_value(profile.honorific):
        desc_parts.append(f"**Honorific:** {profile.honorific}")
    if _has_value(profile.name):
        desc_parts.append(f"**Name:** {profile.name}")
    if _has_value(profile.pronouns):
        desc_parts.append(f"**Pronouns:** {profile.pronouns}")
    if _has_value(profile.age):
        desc_parts.append(f"**Age:** {profile.age}")
    if _has_value(profile.tribute_price):
        desc_parts.append(f"**Tribute:** {profile.tribute_price}")
    desc_parts.append("Age Verified ✅" if is_verified else "Age Verified ❌")

    text = f"## ✦ {display_name}\n" + "\n".join(desc_parts)
    section = discord.ui.Section(
        discord.ui.TextDisplay(text),
        accessory=discord.ui.Thumbnail(member.display_avatar.url),
    )
    items: list[discord.ui.Section | discord.ui.TextDisplay] = [section]

    # Throne — shown as its own field since it's a link
    if _has_value(profile.throne):
        items.append(discord.ui.TextDisplay(f"**Throne**\n{profile.throne}"))

    # Payment links — smart-labelled
    pay_lines = [
        line for url in (
            profile.payment_link1,
            profile.payment_link2,
            profile.payment_link3,
            profile.payment_link4,
        )
        if (line := _smart_link_line(url))
    ]
    if pay_lines:
        _add_chunked_text_displays(items, name="Payment Links", lines=pay_lines)

    # Content links — smart-labelled
    content_lines = [
        line for url in (
            profile.content_link1,
            profile.content_link2,
            profile.content_link3,
            profile.content_link4,
        )
        if (line := _smart_link_line(url))
    ]
    if content_lines:
        _add_chunked_text_displays(items, name="Content Links", lines=content_lines)

    # Kinks & Limits
    if _has_value(profile.kinks):
        items.append(discord.ui.TextDisplay(f"**Kinks**\n{profile.kinks}"))
    if _has_value(profile.limits):
        items.append(discord.ui.TextDisplay(f"**Limits**\n{profile.limits}"))

    # Throne tracking badge
    if profile.throne_tracking_enabled:
        items.append(discord.ui.TextDisplay("**Features**\n✓ Throne tracking enabled"))

    try:
        created = datetime.fromisoformat(profile.created_at)
        created_label = created.strftime("%m/%d/%Y")
    except ValueError:
        created_label = profile.created_at
    items.append(discord.ui.TextDisplay(_butler_footer(f"Domme profile • Created {created_label}")))
    return discord.ui.Container(*items, accent_color=discord.Color(profile.profile_color))


def domme_send_leaderboard_container(
    sends: list[ThroneSend],
    member: discord.Member | discord.User,
) -> discord.ui.Container:
    """Personal leaderboard container shown to a Domme for sends they've received."""
    display_name = member.display_name if isinstance(member, discord.Member) else member.name

    if not sends:
        return _styled_container(
            title=f"💸 {display_name}'s Sends Leaderboard",
            description="No sends recorded yet.",
            color=PURPLE,
            footer=_butler_footer("Throne tracking"),
        )

    # Group by sub using a collision-free prefixed key and count sends.
    from collections import defaultdict

    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    labels: dict[str, str] = {}
    for send in sends:
        if send.claimed_sub_user_id:
            key = f"uid:{send.claimed_sub_user_id}"
        elif send.sub_throne_name:
            key = f"name:{send.sub_throne_name.lower()}"
        else:
            key = "anonymous"
        counts[key] += 1
        totals[key] += send.amount_usd
        if key not in labels:
            if send.claimed_sub_user_id:
                labels[key] = f"<@{send.claimed_sub_user_id}>"
            elif send.sub_throne_name:
                labels[key] = f"{send.sub_throne_name} *(Unclaimed)*"
            else:
                labels[key] = "*Unclaimed*"

    sorted_entries = sorted(
        counts.items(),
        key=lambda x: (x[1], totals[x[0]]),
        reverse=True,
    )
    lines = []
    for key, count in sorted_entries[:20]:
        total = totals[key]
        send_word = "send" if count == 1 else "sends"
        if total > 0:
            lines.append(f"**{labels[key]}** — {count} {send_word} (${total:,.2f})")
        else:
            lines.append(f"**{labels[key]}** — {count} {send_word}")
    total_all = sum(totals.values())
    total_count = sum(counts.values())
    if total_all > 0:
        footer = f"Total sends: {total_count} • Total received: ${total_all:,.2f}"
    else:
        footer = f"Total sends: {total_count}"

    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(f"## 💸 {display_name}'s Sends Leaderboard\n" + "\n".join(lines)),
        discord.ui.TextDisplay(_butler_footer(footer)),
    ]
    return discord.ui.Container(*items, accent_color=PURPLE)


def server_leaderboard_container(
    rows: list[LeaderboardRow],
    bot: discord.Client,
) -> discord.ui.Container:
    """Server-wide leaderboard container (updated every 5 minutes)."""
    if not rows:
        return _styled_container(
            title="🏆 Server Sends Leaderboard",
            description="No sends recorded yet. Be the first!",
            color=PURPLE,
            footer=_butler_footer("Leaderboard • Updates every 5 minutes"),
        )

    lines: list[str] = []
    for row in rows:
        if row.claimed_sub_user_id:
            sub_label = f"<@{row.claimed_sub_user_id}>"
        elif row.sub_throne_name:
            sub_label = f"{row.sub_throne_name} *(Unclaimed)*"
        else:
            sub_label = "*Unclaimed*"
        domme_label = f"<@{row.domme_user_id}>"
        send_word = "send" if row.send_count == 1 else "sends"
        if row.total_usd > 0:
            score = f"**{row.send_count} {send_word}** (${row.total_usd:,.2f})"
        else:
            score = f"**{row.send_count} {send_word}**"
        lines.append(f"{sub_label} ~ {domme_label}     {score}")

    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay("## 🏆 Server Sends Leaderboard\n" + "\n".join(lines)),
        discord.ui.TextDisplay(_butler_footer("Leaderboard • Updates every 5 minutes")),
    ]
    return discord.ui.Container(*items, accent_color=PURPLE)


def throne_send_log_container(
    send: ThroneSend,
    domme: discord.Member | discord.User | None,
) -> discord.ui.Container:
    """Container posted to the sends channel when a send is logged."""
    domme_label = domme.mention if domme else f"<@{send.domme_user_id}>"
    if send.claimed_sub_user_id:
        sub_label = f"<@{send.claimed_sub_user_id}>"
        if send.sub_throne_name:
            sub_label += f" ({send.sub_throne_name})"
    elif send.sub_throne_name:
        sub_label = f"{send.sub_throne_name} *(Unclaimed)*"
    else:
        sub_label = "*Unclaimed*"

    if send.is_private:
        amount_str = "*Private*"
    else:
        amount_str = f"**${send.amount_usd:,.2f}**"

    desc_lines = [
        f"**To:** {domme_label}",
        f"**From:** {sub_label}",
        f"**Amount:** {amount_str}",
    ]
    if send.item_name:
        desc_lines.append(f"**Item:** {send.item_name}")

    items: list[discord.ui.TextDisplay | discord.ui.MediaGallery] = [
        discord.ui.TextDisplay(f"## 💸 New Send Received!\n" + "\n".join(desc_lines)),
    ]
    if send.item_image_url:
        items.append(discord.ui.MediaGallery(discord.ui.MediaGalleryItem(send.item_image_url)))
    items.append(discord.ui.TextDisplay(_butler_footer(f"Throne send #{send.id}")))
    return discord.ui.Container(*items, accent_color=GREEN)


def sub_profile_container(
    profile: SubProfile,
    member: discord.Member | discord.User,
    *,
    is_verified: bool = False,
    rank: int | None = None,
    owned_by_member: discord.Member | discord.User | None = None,
) -> discord.ui.Container:
    display_name = member.display_name if isinstance(member, discord.Member) else member.name

    # Build a clean description block
    desc_parts: list[str] = []
    if _has_value(profile.name):
        desc_parts.append(f"**Name:** {profile.name}")
    if _has_value(profile.pronouns):
        desc_parts.append(f"**Pronouns:** {profile.pronouns}")
    if _has_value(profile.age):
        desc_parts.append(f"**Age:** {profile.age}")
    if profile.throne_name:
        rank_str = f"#{rank}" if rank is not None else "Unranked"
        desc_parts.append(f"**Throne Name:** {profile.throne_name} ({rank_str})")
    desc_parts.append("Age Verified ✅" if is_verified else "Age Verified ❌")

    owner_label: str | None = None
    if owned_by_member is not None:
        owner_label = owned_by_member.mention
    elif profile.owned_by_domme_user_id:
        owner_label = f"<@{profile.owned_by_domme_user_id}>"
    if owner_label:
        desc_parts.append(f"**Owned By:** {owner_label}")

    color = discord.Color(profile.profile_color) if profile.profile_color else SOFT_DARK

    text = f"## ✦ {display_name}\n" + "\n".join(desc_parts)
    section = discord.ui.Section(
        discord.ui.TextDisplay(text),
        accessory=discord.ui.Thumbnail(member.display_avatar.url),
    )
    items: list[discord.ui.Section | discord.ui.TextDisplay] = [section]

    if _has_value(profile.kinks):
        items.append(discord.ui.TextDisplay(f"**Kinks**\n{profile.kinks}"))
    if _has_value(profile.limits):
        items.append(discord.ui.TextDisplay(f"**Limits**\n{profile.limits}"))

    try:
        created = datetime.fromisoformat(profile.created_at)
        created_label = created.strftime("%m/%d/%Y")
    except ValueError:
        created_label = profile.created_at
    items.append(discord.ui.TextDisplay(_butler_footer(f"Sub profile • Created {created_label}")))
    return discord.ui.Container(*items, accent_color=color)


def sub_setup_intro_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.SUB_SETUP_INTRO_TITLE,
        description=messages.SUB_SETUP_INTRO_DESCRIPTION,
        color=SOFT_DARK,
        footer=_butler_footer("Sub profile setup"),
    )


def sub_setup_name_container(*, throne_name: str | None) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.SUB_SETUP_NAME_TITLE}\n{messages.SUB_SETUP_NAME_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Your Throne Name**\n{_profile_value(throne_name)}"),
        discord.ui.TextDisplay(_butler_footer("Step 1/6")),
    ]
    return discord.ui.Container(*items, accent_color=SOFT_DARK)


def sub_setup_details_container(
    *,
    name: str | None,
    pronouns: str | None,
    age: str | None,
) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.SUB_SETUP_DETAILS_TITLE}\n{messages.SUB_SETUP_DETAILS_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Name**\n{_profile_value(name)}"),
        discord.ui.TextDisplay(f"**Pronouns:** {_profile_value(pronouns)} | **Age:** {_profile_value(age)}"),
        discord.ui.TextDisplay(_butler_footer("Step 2/6")),
    ]
    return discord.ui.Container(*items, accent_color=SOFT_DARK)


def sub_setup_kinks_limits_container(
    *,
    kinks: str | None,
    limits: str | None,
) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.SUB_SETUP_KINKS_LIMITS_TITLE}\n{messages.SUB_SETUP_KINKS_LIMITS_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Kinks**\n{_profile_value(kinks)}"),
        discord.ui.TextDisplay(f"**Limits**\n{_profile_value(limits)}"),
        discord.ui.TextDisplay(_butler_footer("Step 3/6")),
    ]
    return discord.ui.Container(*items, accent_color=SOFT_DARK)


def sub_setup_color_container(*, profile_color: int) -> discord.ui.Container:
    color = discord.Color(profile_color)
    label = next(
        (lbl for val, _emoji, lbl in PROFILE_COLOR_PRESETS if val == profile_color),
        f"Custom (#{profile_color:06X})",
    )
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.SUB_SETUP_COLOR_TITLE}\n{messages.SUB_SETUP_COLOR_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Selected Colour**\n{label}"),
        discord.ui.TextDisplay(_butler_footer("Step 4/6")),
    ]
    return discord.ui.Container(*items, accent_color=color)


def sub_setup_owner_container(*, owned_by_label: str) -> discord.ui.Container:
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.SUB_SETUP_OWNER_TITLE}\n{messages.SUB_SETUP_OWNER_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(f"**Currently Selected**\n{owned_by_label}"),
        discord.ui.TextDisplay(_butler_footer("Step 5/6")),
    ]
    return discord.ui.Container(*items, accent_color=SOFT_DARK)


def sub_setup_review_container(
    *,
    throne_name: str | None,
    name: str | None,
    pronouns: str | None,
    age: str | None,
    profile_color: int,
    kinks: str | None,
    limits: str | None,
    owned_by_label: str,
) -> discord.ui.Container:
    color_label = next(
        (lbl for val, _emoji, lbl in PROFILE_COLOR_PRESETS if val == profile_color),
        f"#{profile_color:06X}",
    )
    items: list[discord.ui.TextDisplay] = [
        discord.ui.TextDisplay(
            f"## {messages.SUB_SETUP_REVIEW_TITLE}\n{messages.SUB_SETUP_REVIEW_DESCRIPTION}"
        ),
        discord.ui.TextDisplay(
            f"**Identity**\n"
            f"**Name:** {_profile_value(name)}\n"
            f"**Pronouns:** {_profile_value(pronouns)}\n"
            f"**Age:** {_profile_value(age)}"
        ),
        discord.ui.TextDisplay(
            f"**Throne Name:** {_profile_value(throne_name)} | **Profile Colour:** {color_label}"
        ),
        discord.ui.TextDisplay(f"**Owned By**\n{owned_by_label}"),
    ]
    if _has_value(kinks):
        items.append(discord.ui.TextDisplay(f"**Kinks**\n{kinks}"))
    if _has_value(limits):
        items.append(discord.ui.TextDisplay(f"**Limits**\n{limits}"))
    items.append(discord.ui.TextDisplay(_butler_footer("Step 6/6 — Ready to save")))
    return discord.ui.Container(*items, accent_color=discord.Color(profile_color))


def sub_setup_complete_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.SUB_SETUP_COMPLETE_TITLE,
        description=messages.SUB_SETUP_COMPLETE_DESCRIPTION,
        color=GREEN,
        footer=_butler_footer("Profile saved"),
    )


def sub_setup_later_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.SUB_SETUP_LATER_TITLE,
        description=messages.SUB_SETUP_LATER_DESCRIPTION,
        color=SOFT_DARK,
        footer=_butler_footer("Setup paused"),
    )


def sub_setup_cancelled_container() -> discord.ui.Container:
    return _styled_container(
        title=messages.SUB_SETUP_CANCELLED_TITLE,
        description=messages.SUB_SETUP_CANCELLED_DESCRIPTION,
        color=SOFT_DARK,
        footer=_butler_footer("Setup cancelled"),
    )
