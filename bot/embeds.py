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


def _styled_embed(
    *,
    title: str,
    description: str | None = None,
    color: discord.Color,
    timestamp: datetime | None = None,
) -> discord.Embed:
    return discord.Embed(title=title, description=description, color=color, timestamp=timestamp)


def _set_butler_footer(embed: discord.Embed, detail: str) -> None:
    """Mutate an embed in place to apply the standard Butler footer format."""
    embed.set_footer(text=f"The Butler • {detail}")


def _profile_value(value: str | None) -> str:
    return value.strip() if value and value.strip() else "Not provided"


def _feature_value(enabled: bool) -> str:
    return "Yes" if enabled else "No"


def _add_chunked_field(
    embed: discord.Embed,
    *,
    name: str,
    lines: list[str],
) -> None:
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
        embed.add_field(name=heading, value=chunk, inline=False)


def _smart_link_line(url: str | None) -> str | None:
    """Return 'Label: URL' if url is set, otherwise None."""
    if not url or not url.strip():
        return None
    label = detect_platform(url.strip())
    return f"**{label}:** {url.strip()}"


def _has_value(value: str | None) -> bool:
    return bool(value and value.strip())


def welcome_embed(member: discord.Member) -> discord.Embed:
    embed = _styled_embed(
        title=messages.WELCOME_TITLE,
        description=messages.WELCOME_DESCRIPTION.format(user_mention=member.mention),
        color=PINK,
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    _set_butler_footer(embed, "18+ verification required")
    return embed


def verification_panel_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.VERIFICATION_PANEL_TITLE,
        description=messages.VERIFICATION_PANEL_DESCRIPTION,
        color=PURPLE,
    )
    _set_butler_footer(embed, "Age verification")
    return embed


def initial_verification_dm_embed(notice: str | None = None) -> discord.Embed:
    embed = _styled_embed(
        title=messages.INITIAL_VERIFICATION_DM_TITLE,
        description=messages.INITIAL_VERIFICATION_DM_DESCRIPTION,
        color=PURPLE,
    )
    if notice:
        embed.add_field(name="Invalid Submission", value=notice, inline=False)
    _set_butler_footer(embed, "Verification expires in 5 minutes")
    return embed


def role_prompt_embed(selected_role: str | None = None) -> discord.Embed:
    embed = _styled_embed(
        title=messages.ROLE_PROMPT_TITLE,
        description=messages.ROLE_PROMPT_DESCRIPTION,
        color=PINK,
    )
    if selected_role:
        embed.add_field(name="Selected Role", value=selected_role, inline=False)
    _set_butler_footer(embed, "Role selection")
    return embed


def pending_review_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.PENDING_REVIEW_TITLE,
        description=messages.PENDING_REVIEW_DESCRIPTION,
        color=PURPLE,
    )
    _set_butler_footer(embed, "Staff review pending")
    return embed


def approved_dm_embed(config: BotConfig) -> discord.Embed:
    embed = _styled_embed(
        title=messages.APPROVED_DM_TITLE,
        description=messages.APPROVED_DM_DESCRIPTION.format(
            roles_channel=mention_channel(config.roles_channel_id),
            introductions_channel=mention_channel(config.introductions_channel_id),
            general_channel=mention_channel(config.general_channel_id),
        ),
        color=GREEN,
    )
    _set_butler_footer(embed, "Welcome to The Drain Gang")
    return embed


def denied_underage_dm_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.DENIED_UNDERAGE_DM_TITLE,
        description=messages.DENIED_UNDERAGE_DM_DESCRIPTION,
        color=RED,
    )
    _set_butler_footer(embed, "Verification denied")
    return embed


def denied_invalid_dm_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.DENIED_INVALID_DM_TITLE,
        description=messages.DENIED_INVALID_DM_DESCRIPTION,
        color=ORANGE,
    )
    _set_butler_footer(embed, "Verification denied")
    return embed


def session_expired_dm_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.SESSION_EXPIRED_DM_TITLE,
        description=messages.SESSION_EXPIRED_DM_DESCRIPTION,
        color=SOFT_DARK,
    )
    _set_butler_footer(embed, "Verification expired")
    return embed


def invalid_submission_dm_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.INVALID_SUBMISSION_DM_TITLE,
        description=messages.INVALID_SUBMISSION_DM_DESCRIPTION,
        color=ORANGE,
    )
    _set_butler_footer(embed, "Try again")
    return embed


def verification_log_embed(
    request: VerificationRequest,
    member: discord.Member | None,
) -> discord.Embed:
    nickname_or_username = member.display_name if member else request.username
    verification_value = request.verification_value or "Not provided"
    verification_display = verification_value
    if request.verification_type == "Photo":
        verification_display = "Photo submitted below."

    embed = _styled_embed(
        title="New Age Verification Request",
        description=(
            f"**User:** {user_mention(request.user_id)} ({nickname_or_username})\n\n"
            f"**Verification Type:** {request.verification_type or 'Unknown'}\n\n"
            f"**Verification:**\n{verification_display}\n\n"
            f"**User has marked they are a {request.selected_role or 'Unknown'}**"
        ),
        color=PURPLE,
        timestamp=discord.utils.utcnow(),
    )
    if member:
        embed.set_thumbnail(url=member.display_avatar.url)
    if request.verification_type == "Photo" and request.verification_value:
        embed.set_image(url=request.verification_value)
    _set_butler_footer(embed, f"Request ID #{request.id}")
    return embed


def verification_outcome_embed(
    *,
    request: VerificationRequest,
    moderator: discord.Member | discord.User,
    title: str,
    color: discord.Color,
    status: str,
) -> discord.Embed:
    embed = _styled_embed(title=title, color=color)
    embed.add_field(
        name="User",
        value=f"{user_mention(request.user_id)} ({request.username})",
        inline=False,
    )
    embed.add_field(
        name="Selected Role",
        value=request.selected_role or "Unknown",
        inline=False,
    )
    embed.add_field(
        name="Verification Date",
        value=discord.utils.utcnow().strftime("%m/%d/%Y"),
        inline=False,
    )
    embed.add_field(
        name="Mod Responsible for Verification",
        value=f"{moderator.name} ({moderator.mention})",
        inline=False,
    )
    embed.add_field(
        name="Verification method",
        value=request.verification_type or "Unknown",
        inline=False,
    )
    embed.add_field(name="Status", value=status, inline=False)
    _set_butler_footer(embed, f"Request ID #{request.id}")
    return embed


def verification_status_embed(
    request: VerificationRequest | None,
    user: discord.User | discord.Member,
) -> discord.Embed:
    embed = _styled_embed(title="Verification Status", color=PURPLE)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.add_field(name="User", value=f"{user.mention} ({user.name})", inline=False)

    if request is None:
        embed.description = "No verification record was found for this user."
    else:
        embed.add_field(name="Status", value=request.status, inline=True)
        embed.add_field(
            name="Selected Role",
            value=request.selected_role or "Not selected",
            inline=True,
        )
        embed.add_field(
            name="Verification method",
            value=request.verification_type or "Not submitted",
            inline=True,
        )
        embed.add_field(name="Submitted", value=request.submitted_at, inline=False)
        if request.reviewed_at:
            embed.add_field(name="Reviewed", value=request.reviewed_at, inline=False)
    _set_butler_footer(embed, "Staff only")
    return embed


def verification_cleanup_embed(
    *,
    role: discord.Role,
    members: list[discord.Member],
) -> discord.Embed:
    embed = _styled_embed(title="Unverified Cleanup", color=PURPLE)
    embed.description = f"Users who still have {role.mention}: **{len(members)}**"
    if members:
        visible_members = members[:25]
        lines = [f"• {member.mention} ({member.display_name})" for member in visible_members]
        if len(members) > len(visible_members):
            lines.append(f"• +{len(members) - len(visible_members)} more")
        embed.add_field(name="Members", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Members", value="No users currently have this role.", inline=False)
    _set_butler_footer(embed, "Staff only")
    return embed


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


def help_page_embed(
    page_index: int,
    total_pages: int,
    pages: list[tuple[str, int, str, tuple[tuple[str, str], ...]]] | None = None,
) -> discord.Embed:
    if pages is None:
        # Fallback: show a generic page list when called without a roles context.
        pages = build_help_pages(is_domme=True, is_sub=True, is_moderator=True)
    # Clamp the page index defensively in case the caller passes a stale value.
    page_index = max(0, min(page_index, len(pages) - 1))
    section, color, blurb, entries = pages[page_index]
    embed = _styled_embed(
        title=f"The Butler Help • {section}",
        description=blurb,
        color=color,
    )
    for name, description in entries:
        embed.add_field(name=name, value=description, inline=False)
    _set_butler_footer(embed, f"Help page {page_index + 1}/{total_pages}")
    return embed


def reaction_role_embed(
    *,
    title: str,
    description: str,
    color: discord.Color,
    mappings: list[tuple[str, str]],
    creator: discord.abc.User,
) -> discord.Embed:
    embed = _styled_embed(
        title=title.strip() or "Reaction Roles",
        description=description.strip(),
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    lines = [f"{emoji} = {role_mention}" for emoji, role_mention in mappings]
    embed.add_field(name="Role Reactions", value="\n".join(lines), inline=False)
    _set_butler_footer(embed, f"Reaction roles • Setup by {creator.name}")
    return embed


def reaction_role_created_embed(
    jump_url: str,
    channel: discord.TextChannel,
    mappings: list[tuple[str, str, discord.Role]],
) -> discord.Embed:
    embed = _styled_embed(
        title="Reaction-role message created",
        color=GREEN,
    )
    embed.add_field(name="Channel", value=channel.mention, inline=True)
    embed.add_field(name="Mappings", value=str(len(mappings)), inline=True)
    embed.add_field(name="Message", value=f"[Jump to message]({jump_url})", inline=False)
    _set_butler_footer(embed, "Reaction roles ready")
    return embed


def domme_setup_intro_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.DOMME_SETUP_INTRO_TITLE,
        description=messages.DOMME_SETUP_INTRO_DESCRIPTION,
        color=PINK,
    )
    embed.set_footer(text="The Butler • Domme profile setup")
    return embed


def domme_setup_name_embed(*, name: str | None, honorific: str | None) -> discord.Embed:
    embed = _styled_embed(
        title=messages.DOMME_SETUP_NAME_TITLE,
        description=messages.DOMME_SETUP_NAME_DESCRIPTION,
        color=PINK,
    )
    embed.add_field(name="Name", value=_profile_value(name), inline=False)
    embed.add_field(name="Honorific", value=_profile_value(honorific), inline=False)
    embed.set_footer(text="The Butler • Step 1/4")
    return embed


def domme_setup_details_embed(
    *,
    pronouns: str | None,
    age: str | None,
    tribute_price: str | None,
    kinks: str | None,
    limits: str | None,
) -> discord.Embed:
    embed = _styled_embed(
        title=messages.DOMME_SETUP_DETAILS_TITLE,
        description=messages.DOMME_SETUP_DETAILS_DESCRIPTION,
        color=PURPLE,
    )
    embed.add_field(name="Pronouns", value=_profile_value(pronouns), inline=False)
    embed.add_field(name="Age", value=_profile_value(age), inline=True)
    embed.add_field(name="Tribute Fee Price", value=_profile_value(tribute_price), inline=True)
    embed.add_field(name="Kinks", value=_profile_value(kinks), inline=False)
    embed.add_field(name="Limits", value=_profile_value(limits), inline=False)
    embed.set_footer(text="The Butler • Step 2/4")
    return embed


def domme_setup_links_embed(
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
) -> discord.Embed:
    embed = _styled_embed(
        title=messages.DOMME_SETUP_PAYMENTS_TITLE,
        description=messages.DOMME_SETUP_PAYMENTS_DESCRIPTION,
        color=PURPLE,
    )
    embed.add_field(name="Throne", value=_profile_value(throne), inline=False)
    embed.add_field(name="Tribute Link", value=_profile_value(tribute_link), inline=False)
    # Payment links — show smart-detected labels
    pay_lines = [
        line for link in (payment_link1, payment_link2, payment_link3, payment_link4)
        if (line := _smart_link_line(link))
    ]
    embed.add_field(
        name="Payment Links",
        value="\n".join(pay_lines) if pay_lines else "Not provided",
        inline=False,
    )
    # Content links — smart-detected labels
    content_lines = [
        line for link in (content_link1, content_link2, content_link3, content_link4)
        if (line := _smart_link_line(link))
    ]
    embed.add_field(
        name="Content Links",
        value="\n".join(content_lines) if content_lines else "Not provided",
        inline=False,
    )
    embed.set_footer(text="The Butler • Step 3/4")
    return embed


def domme_setup_throne_embed(*, throne: str | None) -> discord.Embed:
    embed = _styled_embed(
        title=messages.DOMME_SETUP_THRONE_TITLE,
        description=messages.DOMME_SETUP_THRONE_DESCRIPTION,
        color=PINK,
    )
    embed.add_field(name="Throne", value=_profile_value(throne), inline=False)
    embed.set_footer(text="The Butler • Throne tracking (optional)")
    return embed


def domme_setup_color_embed(*, profile_color: int) -> discord.Embed:
    color = discord.Color(profile_color)
    # Find the matching preset label if any
    label = next(
        (lbl for val, _emoji, lbl in PROFILE_COLOR_PRESETS if val == profile_color),
        f"Custom (#{profile_color:06X})",
    )
    embed = _styled_embed(
        title=messages.DOMME_SETUP_COLOR_TITLE,
        description=messages.DOMME_SETUP_COLOR_DESCRIPTION,
        color=color,
    )
    embed.add_field(name="Selected Color", value=label, inline=False)
    embed.set_footer(text="The Butler • Step 4/4")
    return embed


def domme_setup_review_embed(
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
) -> discord.Embed:
    embed = _styled_embed(
        title=messages.DOMME_SETUP_REVIEW_TITLE,
        description=messages.DOMME_SETUP_REVIEW_DESCRIPTION,
        color=discord.Color(profile_color),
    )
    embed.add_field(
        name="Identity",
        value=(
            f"**Name:** {_profile_value(name)}\n"
            f"**Honorific:** {_profile_value(honorific)}\n"
            f"**Pronouns:** {_profile_value(pronouns)}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Details",
        value=(
            f"**Age:** {_profile_value(age)}\n"
            f"**Tribute Fee Price:** {_profile_value(tribute_price)}"
        ),
        inline=False,
    )
    if _has_value(kinks):
        embed.add_field(name="Kinks", value=kinks, inline=False)
    if _has_value(limits):
        embed.add_field(name="Limits", value=limits, inline=False)
    # Throne + tribute
    embed.add_field(name="Throne", value=_profile_value(throne), inline=True)
    embed.add_field(name="Tribute Link", value=_profile_value(tribute_link), inline=True)
    # Payment links
    pay_lines = [
        line for link in (payment_link1, payment_link2, payment_link3, payment_link4)
        if (line := _smart_link_line(link))
    ]
    embed.add_field(
        name="Payment Links",
        value="\n".join(pay_lines) if pay_lines else "None",
        inline=False,
    )
    # Content links
    content_lines = [
        line for link in (content_link1, content_link2, content_link3, content_link4)
        if (line := _smart_link_line(link))
    ]
    embed.add_field(
        name="Content Links",
        value="\n".join(content_lines) if content_lines else "None",
        inline=False,
    )
    embed.add_field(name="Throne Tracking", value=_feature_value(throne_tracking_enabled), inline=True)
    color_label = next(
        (lbl for val, _emoji, lbl in PROFILE_COLOR_PRESETS if val == profile_color),
        f"#{profile_color:06X}",
    )
    embed.add_field(name="Profile Color", value=color_label, inline=True)
    embed.set_footer(text="The Butler • Ready to save")
    return embed


def domme_setup_complete_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.DOMME_SETUP_COMPLETE_TITLE,
        description=messages.DOMME_SETUP_COMPLETE_DESCRIPTION,
        color=GREEN,
    )
    embed.set_footer(text="The Butler • Profile saved")
    return embed


def domme_setup_later_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.DOMME_SETUP_LATER_TITLE,
        description=messages.DOMME_SETUP_LATER_DESCRIPTION,
        color=SOFT_DARK,
    )
    embed.set_footer(text="The Butler • Setup paused")
    return embed


def domme_setup_cancelled_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.DOMME_SETUP_CANCELLED_TITLE,
        description=messages.DOMME_SETUP_CANCELLED_DESCRIPTION,
        color=SOFT_DARK,
    )
    embed.set_footer(text="The Butler • Setup cancelled")
    return embed


def domme_profile_embed(
    profile: DommeProfile,
    member: discord.Member | discord.User,
    *,
    is_verified: bool = False,
) -> discord.Embed:
    display_name = member.display_name if isinstance(member, discord.Member) else member.name

    # Build identity description — only include fields with values
    identity_parts: list[str] = []
    if _has_value(profile.honorific):
        identity_parts.append(f"**Honorific:** {profile.honorific}")
    if _has_value(profile.name):
        identity_parts.append(f"**Name:** {profile.name}")
    if _has_value(profile.pronouns):
        identity_parts.append(f"**Pronouns:** {profile.pronouns}")
    identity_parts.append("Age Verified ✅" if is_verified else "Age Verified ❌")

    embed = _styled_embed(
        title=f"✦ {display_name}",
        description="\n".join(identity_parts),
        color=discord.Color(profile.profile_color),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    # Details — only show if at least one is set
    details_parts: list[str] = []
    if _has_value(profile.age):
        details_parts.append(f"**Age:** {profile.age}")
    if _has_value(profile.tribute_price):
        details_parts.append(f"**Tribute:** {profile.tribute_price}")
    if details_parts:
        embed.add_field(name="Details", value="\n".join(details_parts), inline=False)

    # Throne — shown separately at the top of links
    if _has_value(profile.throne):
        embed.add_field(name="Throne", value=profile.throne, inline=False)

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
        _add_chunked_field(embed, name="Payment Links", lines=pay_lines)

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
        _add_chunked_field(embed, name="Content Links", lines=content_lines)

    # Kinks & Limits
    if _has_value(profile.kinks):
        embed.add_field(name="Kinks", value=profile.kinks, inline=False)
    if _has_value(profile.limits):
        embed.add_field(name="Limits", value=profile.limits, inline=False)

    # Throne tracking badge
    if profile.throne_tracking_enabled:
        embed.add_field(name="Features", value="✓ Throne tracking enabled", inline=False)

    try:
        created = datetime.fromisoformat(profile.created_at)
        created_label = created.strftime("%m/%d/%Y")
    except ValueError:
        created_label = profile.created_at
    _set_butler_footer(embed, f"Domme profile • Created {created_label}")
    return embed


def domme_send_leaderboard_embed(
    sends: list[ThroneSend],
    member: discord.Member | discord.User,
) -> discord.Embed:
    """Personal leaderboard embed shown to a Domme for sends they've received."""
    display_name = member.display_name if isinstance(member, discord.Member) else member.name
    embed = _styled_embed(
        title=f"💸 {display_name}'s Sends Leaderboard",
        color=PURPLE,
        timestamp=discord.utils.utcnow(),
    )
    if not sends:
        embed.description = "No sends recorded yet."
        _set_butler_footer(embed, "Throne tracking")
        return embed

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
    embed.description = "\n".join(lines) if lines else "No sends recorded yet."
    total_count = sum(counts.values())
    if total_all > 0:
        footer = f"Total sends: {total_count} • Total received: ${total_all:,.2f}"
    else:
        footer = f"Total sends: {total_count}"
    _set_butler_footer(embed, footer)
    return embed


def server_leaderboard_embed(
    rows: list[LeaderboardRow],
    bot: discord.Client,
) -> discord.Embed:
    """Server-wide leaderboard embed (updated every 5 minutes)."""
    embed = _styled_embed(
        title="🏆 Server Sends Leaderboard",
        color=PURPLE,
        timestamp=discord.utils.utcnow(),
    )
    if not rows:
        embed.description = "No sends recorded yet. Be the first!"
        _set_butler_footer(embed, "Leaderboard • Updates every 5 minutes")
        return embed

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

    embed.description = "\n".join(lines)
    _set_butler_footer(embed, "Leaderboard • Updates every 5 minutes")
    return embed


def throne_send_log_embed(
    send: ThroneSend,
    domme: discord.Member | discord.User | None,
) -> discord.Embed:
    """Embed posted to the sends channel when a send is logged."""
    domme_label = domme.mention if domme else f"<@{send.domme_user_id}>"
    if send.claimed_sub_user_id:
        sub_label = f"<@{send.claimed_sub_user_id}>"
        if send.sub_throne_name:
            sub_label += f" ({send.sub_throne_name})"
    elif send.sub_throne_name:
        sub_label = f"{send.sub_throne_name} *(Unclaimed)*"
    else:
        sub_label = "*Unclaimed*"

    embed = _styled_embed(
        title="💸 New Send Received!",
        color=GREEN,
        timestamp=discord.utils.utcnow(),
    )
    embed.add_field(name="Domme", value=domme_label, inline=True)
    embed.add_field(name="From", value=sub_label, inline=True)
    if send.is_private:
        amount_value = "*Private*"
    else:
        amount_value = f"**${send.amount_usd:,.2f}**"
    embed.add_field(name="Amount", value=amount_value, inline=True)
    if send.item_name:
        embed.add_field(name="Item", value=send.item_name, inline=False)
    if send.item_image_url:
        embed.set_image(url=send.item_image_url)
    _set_butler_footer(embed, f"Throne send #{send.id}")
    return embed


def sub_profile_embed(
    profile: SubProfile,
    member: discord.Member | discord.User,
    *,
    is_verified: bool = False,
    rank: int | None = None,
    owned_by_member: discord.Member | discord.User | None = None,
) -> discord.Embed:
    display_name = member.display_name if isinstance(member, discord.Member) else member.name

    # Build description with identity fields
    identity_parts: list[str] = []
    if _has_value(profile.name):
        identity_parts.append(f"**Name:** {profile.name}")
    if _has_value(profile.pronouns):
        identity_parts.append(f"**Pronouns:** {profile.pronouns}")
    if _has_value(profile.age):
        identity_parts.append(f"**Age:** {profile.age}")
    identity_parts.append("Age Verified ✅" if is_verified else "Age Verified ❌")

    color = discord.Color(profile.profile_color) if profile.profile_color else SOFT_DARK
    embed = _styled_embed(
        title=f"✦ {display_name}",
        description="\n".join(identity_parts),
        color=color,
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    if profile.throne_name:
        embed.add_field(name="Throne Name", value=profile.throne_name, inline=True)

    if rank is not None:
        embed.add_field(name="Leaderboard Rank", value=f"#{rank}", inline=True)
    elif profile.throne_name:
        embed.add_field(name="Leaderboard Rank", value="Unranked", inline=True)

    if owned_by_member is not None:
        embed.add_field(name="Owned By", value=owned_by_member.mention, inline=False)
    elif profile.owned_by_domme_user_id:
        embed.add_field(name="Owned By", value=f"<@{profile.owned_by_domme_user_id}>", inline=False)

    if _has_value(profile.kinks):
        embed.add_field(name="Kinks", value=profile.kinks, inline=False)
    if _has_value(profile.limits):
        embed.add_field(name="Limits", value=profile.limits, inline=False)

    try:
        created = datetime.fromisoformat(profile.created_at)
        created_label = created.strftime("%m/%d/%Y")
    except ValueError:
        created_label = profile.created_at
    _set_butler_footer(embed, f"Sub profile • Created {created_label}")
    return embed


def sub_setup_intro_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.SUB_SETUP_INTRO_TITLE,
        description=messages.SUB_SETUP_INTRO_DESCRIPTION,
        color=SOFT_DARK,
    )
    embed.set_footer(text="The Butler • Sub profile setup")
    return embed


def sub_setup_name_embed(*, throne_name: str | None) -> discord.Embed:
    embed = _styled_embed(
        title=messages.SUB_SETUP_NAME_TITLE,
        description=messages.SUB_SETUP_NAME_DESCRIPTION,
        color=SOFT_DARK,
    )
    embed.add_field(name="Your Throne Name", value=_profile_value(throne_name), inline=False)
    embed.set_footer(text="The Butler • Step 1/6")
    return embed


def sub_setup_details_embed(
    *,
    name: str | None,
    pronouns: str | None,
    age: str | None,
) -> discord.Embed:
    embed = _styled_embed(
        title=messages.SUB_SETUP_DETAILS_TITLE,
        description=messages.SUB_SETUP_DETAILS_DESCRIPTION,
        color=SOFT_DARK,
    )
    embed.add_field(name="Name", value=_profile_value(name), inline=False)
    embed.add_field(name="Pronouns", value=_profile_value(pronouns), inline=True)
    embed.add_field(name="Age", value=_profile_value(age), inline=True)
    embed.set_footer(text="The Butler • Step 2/6")
    return embed


def sub_setup_kinks_limits_embed(
    *,
    kinks: str | None,
    limits: str | None,
) -> discord.Embed:
    embed = _styled_embed(
        title=messages.SUB_SETUP_KINKS_LIMITS_TITLE,
        description=messages.SUB_SETUP_KINKS_LIMITS_DESCRIPTION,
        color=SOFT_DARK,
    )
    embed.add_field(name="Kinks", value=_profile_value(kinks), inline=False)
    embed.add_field(name="Limits", value=_profile_value(limits), inline=False)
    embed.set_footer(text="The Butler • Step 3/6")
    return embed


def sub_setup_color_embed(*, profile_color: int) -> discord.Embed:
    color = discord.Color(profile_color)
    label = next(
        (lbl for val, _emoji, lbl in PROFILE_COLOR_PRESETS if val == profile_color),
        f"Custom (#{profile_color:06X})",
    )
    embed = _styled_embed(
        title=messages.SUB_SETUP_COLOR_TITLE,
        description=messages.SUB_SETUP_COLOR_DESCRIPTION,
        color=color,
    )
    embed.add_field(name="Selected Colour", value=label, inline=False)
    embed.set_footer(text="The Butler • Step 4/6")
    return embed


def sub_setup_owner_embed(*, owned_by_label: str) -> discord.Embed:
    embed = _styled_embed(
        title=messages.SUB_SETUP_OWNER_TITLE,
        description=messages.SUB_SETUP_OWNER_DESCRIPTION,
        color=SOFT_DARK,
    )
    embed.add_field(name="Currently Selected", value=owned_by_label, inline=False)
    embed.set_footer(text="The Butler • Step 5/6")
    return embed


def sub_setup_review_embed(
    *,
    throne_name: str | None,
    name: str | None,
    pronouns: str | None,
    age: str | None,
    profile_color: int,
    kinks: str | None,
    limits: str | None,
    owned_by_label: str,
) -> discord.Embed:
    color_label = next(
        (lbl for val, _emoji, lbl in PROFILE_COLOR_PRESETS if val == profile_color),
        f"#{profile_color:06X}",
    )
    embed = _styled_embed(
        title=messages.SUB_SETUP_REVIEW_TITLE,
        description=messages.SUB_SETUP_REVIEW_DESCRIPTION,
        color=discord.Color(profile_color),
    )
    embed.add_field(
        name="Identity",
        value=(
            f"**Name:** {_profile_value(name)}\n"
            f"**Pronouns:** {_profile_value(pronouns)}\n"
            f"**Age:** {_profile_value(age)}"
        ),
        inline=False,
    )
    embed.add_field(name="Throne Name", value=_profile_value(throne_name), inline=True)
    embed.add_field(name="Profile Colour", value=color_label, inline=True)
    embed.add_field(name="Owned By", value=owned_by_label, inline=False)
    if _has_value(kinks):
        embed.add_field(name="Kinks", value=kinks, inline=False)
    if _has_value(limits):
        embed.add_field(name="Limits", value=limits, inline=False)
    embed.set_footer(text="The Butler • Step 6/6 — Ready to save")
    return embed


def sub_setup_complete_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.SUB_SETUP_COMPLETE_TITLE,
        description=messages.SUB_SETUP_COMPLETE_DESCRIPTION,
        color=GREEN,
    )
    embed.set_footer(text="The Butler • Profile saved")
    return embed


def sub_setup_later_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.SUB_SETUP_LATER_TITLE,
        description=messages.SUB_SETUP_LATER_DESCRIPTION,
        color=SOFT_DARK,
    )
    embed.set_footer(text="The Butler • Setup paused")
    return embed


def sub_setup_cancelled_embed() -> discord.Embed:
    embed = _styled_embed(
        title=messages.SUB_SETUP_CANCELLED_TITLE,
        description=messages.SUB_SETUP_CANCELLED_DESCRIPTION,
        color=SOFT_DARK,
    )
    embed.set_footer(text="The Butler • Setup cancelled")
    return embed
