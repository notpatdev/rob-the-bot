from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from bot import messages
from bot.embeds import PROFILE_COLOR_PRESETS, build_help_pages, help_page_embed

if TYPE_CHECKING:
    from bot.verification import (
        DommeProfileService,
        DommeProfileSession,
        ReactionRoleService,
        SubProfileService,
        SubProfileSession,
        VerificationService,
    )


def _clean_optional(value: str) -> str | None:
    cleaned = value.strip()
    return cleaned or None


def _disable_all(view: discord.ui.View) -> None:
    for item in view.children:
        if hasattr(item, "disabled"):
            item.disabled = True


class VerificationPanelView(discord.ui.View):
    def __init__(self, service: VerificationService) -> None:
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(
        label="Verify",
        style=discord.ButtonStyle.primary,
        custom_id="verify_start",
    )
    async def verify_start(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.start_verification(interaction)


class RoleSelectionView(discord.ui.View):
    def __init__(self, user_id: int) -> None:
        super().__init__(timeout=300)
        self.user_id = user_id
        self.selection: str | None = None
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "This role selection is not for you.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Domme", style=discord.ButtonStyle.secondary)
    async def domme(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self._select(interaction, "Domme")

    @discord.ui.button(label="Submissive", style=discord.ButtonStyle.secondary)
    async def submissive(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self._select(interaction, "Submissive")

    async def _select(self, interaction: discord.Interaction, value: str) -> None:
        self.selection = value
        _disable_all(self)
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self) -> None:
        _disable_all(self)
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class StaffReviewView(discord.ui.View):
    def __init__(
        self,
        service: VerificationService | None,
        request_id: int,
        *,
        link_url: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(timeout=None)
        self.service = service
        self.request_id = request_id

        approve = discord.ui.Button(
            label="Approve",
            style=discord.ButtonStyle.success,
            custom_id=f"verification:approve:{request_id}",
            disabled=disabled,
        )
        approve.callback = self._approve
        self.add_item(approve)

        deny_underage = discord.ui.Button(
            label="Deny (Under 18)",
            style=discord.ButtonStyle.danger,
            custom_id=f"verification:deny_underage:{request_id}",
            disabled=disabled,
        )
        deny_underage.callback = self._deny_underage
        self.add_item(deny_underage)

        deny_invalid = discord.ui.Button(
            label="Deny (Invalid Service)",
            style=discord.ButtonStyle.danger,
            custom_id=f"verification:deny_invalid:{request_id}",
            disabled=disabled,
        )
        deny_invalid.callback = self._deny_invalid
        self.add_item(deny_invalid)

        if link_url:
            self.add_item(
                discord.ui.Button(
                    label="Open Link",
                    style=discord.ButtonStyle.link,
                    url=link_url,
                )
            )

    async def _approve(self, interaction: discord.Interaction) -> None:
        if self.service:
            await self.service.review_request(interaction, self.request_id, "approve")

    async def _deny_underage(self, interaction: discord.Interaction) -> None:
        if self.service:
            await self.service.review_request(interaction, self.request_id, "deny_underage")

    async def _deny_invalid(self, interaction: discord.Interaction) -> None:
        if self.service:
            await self.service.review_request(interaction, self.request_id, "deny_invalid")


class FormLinkView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="Open Form",
                style=discord.ButtonStyle.link,
                url=messages.FORM_URL,
            )
        )


class ReactionRoleSetupModal(discord.ui.Modal, title="Create Reaction Role Message"):
    def __init__(self, service: "ReactionRoleService", *, default_channel_id: int) -> None:
        super().__init__(timeout=900)
        self.service = service

        self.channel_id_input = discord.ui.TextInput(
            label="Target Channel ID",
            default=str(default_channel_id),
            required=True,
            max_length=30,
            placeholder="1498996917277954098",
        )
        self.title_input = discord.ui.TextInput(
            label="Embed Title",
            required=True,
            max_length=120,
            placeholder="Choose your roles",
        )
        self.description_input = discord.ui.TextInput(
            label="Embed Description",
            required=True,
            max_length=1500,
            style=discord.TextStyle.paragraph,
            placeholder="React below to get your roles.",
        )
        self.color_input = discord.ui.TextInput(
            label="Embed Colour (hex, optional)",
            required=False,
            max_length=7,
            placeholder="#B565FF",
        )
        self.mappings_input = discord.ui.TextInput(
            label="Emoji = Role ID or role mention (one per line)",
            required=True,
            max_length=1000,
            style=discord.TextStyle.paragraph,
            placeholder="💗 = 1498997125739053087\n🔥 = <@&1498997103400194191>\n<:custom:1234567890> = 1498997148845478051",
        )
        self.add_item(self.channel_id_input)
        self.add_item(self.title_input)
        self.add_item(self.description_input)
        self.add_item(self.color_input)
        self.add_item(self.mappings_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.service.create_message_from_modal(
            interaction=interaction,
            channel_id_raw=self.channel_id_input.value,
            title=self.title_input.value,
            description=self.description_input.value,
            color_raw=self.color_input.value,
            mappings_raw=self.mappings_input.value,
        )


class HelpView(discord.ui.View):
    def __init__(
        self,
        user_id: int,
        pages: list[tuple[str, int, str, tuple[tuple[str, str], ...]]] | None = None,
    ) -> None:
        super().__init__(timeout=180)
        self.user_id = user_id
        self.pages = pages if pages is not None else []
        self.current_page = 0
        self.total_pages = max(1, len(self.pages))

        self.previous_button = discord.ui.Button(
            label="Previous",
            style=discord.ButtonStyle.secondary,
            custom_id=f"help:previous:{user_id}",
        )
        self.previous_button.callback = self._previous
        self.add_item(self.previous_button)

        self.page_button = discord.ui.Button(
            label=f"Page 1/{self.total_pages}",
            style=discord.ButtonStyle.secondary,
            disabled=True,
        )
        self.add_item(self.page_button)

        self.next_button = discord.ui.Button(
            label="Next",
            style=discord.ButtonStyle.secondary,
            custom_id=f"help:next:{user_id}",
        )
        self.next_button.callback = self._next
        self.add_item(self.next_button)

        self.close_button = discord.ui.Button(
            label="Close",
            style=discord.ButtonStyle.danger,
            custom_id=f"help:close:{user_id}",
        )
        self.close_button.callback = self._close
        self.add_item(self.close_button)
        self._sync_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message(
            "Only the user who opened this help menu can navigate it.",
            ephemeral=True,
        )
        return False

    async def _previous(self, interaction: discord.Interaction) -> None:
        self.current_page = max(0, self.current_page - 1)
        await self._update(interaction)

    async def _next(self, interaction: discord.Interaction) -> None:
        self.current_page = min(self.total_pages - 1, self.current_page + 1)
        await self._update(interaction)

    async def _close(self, interaction: discord.Interaction) -> None:
        _disable_all(self)
        await interaction.response.edit_message(
            content="Help menu closed.",
            embed=None,
            view=None,
        )
        self.stop()

    async def _update(self, interaction: discord.Interaction) -> None:
        self._sync_buttons()
        await interaction.response.edit_message(
            embed=help_page_embed(self.current_page, self.total_pages, self.pages),
            view=self,
        )

    def _sync_buttons(self) -> None:
        self.previous_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page >= self.total_pages - 1
        self.page_button.label = f"Page {self.current_page + 1}/{self.total_pages}"


class DommeSetupView(discord.ui.View):
    def __init__(self, service: DommeProfileService, session: DommeProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.session.user_id:
            return True
        await interaction.response.send_message("This setup is not for you.", ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        if self.session.current_view is not self:
            return
        _disable_all(self)
        if self.session.message:
            try:
                await self.session.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.session.current_view = None
        self.service.finish_session(self.session.user_id)


class DommeSetupIntroView(DommeSetupView):
    @discord.ui.button(label="Continue", style=discord.ButtonStyle.primary)
    async def continue_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_name_step(self.session, interaction)

    @discord.ui.button(label="Later", style=discord.ButtonStyle.secondary)
    async def later_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        self.service.finish_session(self.session.user_id)
        await interaction.response.edit_message(
            embed=self.service.build_later_embed(),
            view=None,
        )
        self.stop()


class DommeSetupNameView(DommeSetupView):
    @discord.ui.button(label="Name + Honorific", style=discord.ButtonStyle.primary)
    async def open_modal(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(DommeNameModal(self.service, self.session))

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_details_step(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_intro_step(self.session, interaction)


class DommeSetupDetailsView(DommeSetupView):
    @discord.ui.button(label="Add Details", style=discord.ButtonStyle.primary)
    async def open_modal(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(DommeDetailsModal(self.service, self.session))

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_payments_step(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_name_step(self.session, interaction)


class DommeSetupPaymentsView(DommeSetupView):
    @discord.ui.button(label="Throne & Tribute", style=discord.ButtonStyle.primary)
    async def throne_tribute_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(DommeThroneLinksModal(self.service, self.session))

    @discord.ui.button(label="Payment Links", style=discord.ButtonStyle.primary)
    async def payment_links_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(DommePaymentLinksModal(self.service, self.session))

    @discord.ui.button(label="Content Links", style=discord.ButtonStyle.primary)
    async def content_links_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(DommeContentLinksModal(self.service, self.session))

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def continue_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.advance_after_payments(self.session, interaction)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.advance_after_payments(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_details_step(self.session, interaction)


class DommeSetupThroneView(DommeSetupView):
    @discord.ui.button(label="Sign Up", style=discord.ButtonStyle.success)
    async def sign_up_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        self.session.throne_tracking_enabled = True
        await self.service.show_color_step(self.session, interaction)

    @discord.ui.button(label="Not Now", style=discord.ButtonStyle.secondary)
    async def not_now_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        self.session.throne_tracking_enabled = False
        await self.service.show_color_step(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_payments_step(self.session, interaction)


class DommeSetupColorView(DommeSetupView):
    @discord.ui.select(
        placeholder="Choose a profile colour…",
        options=[
            discord.SelectOption(label=label, value=str(value), emoji=emoji)
            for value, emoji, label in PROFILE_COLOR_PRESETS
        ],
    )
    async def color_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        self.session.profile_color = int(select.values[0])
        await self.service.show_color_step(self.session, interaction)

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def continue_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_review_step(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if self.session.throne:
            await self.service.show_throne_step(self.session, interaction)
        else:
            await self.service.show_payments_step(self.session, interaction)


class DommeSetupReviewView(DommeSetupView):
    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.save_profile(self.session, interaction)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        self.service.finish_session(self.session.user_id)
        await interaction.response.edit_message(
            embed=self.service.build_cancelled_embed(),
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_color_step(self.session, interaction)


class DommeDeleteConfirmView(discord.ui.View):
    def __init__(self, service: DommeProfileService, user_id: int) -> None:
        super().__init__(timeout=120)
        self.service = service
        self.user_id = user_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("This confirmation is not for you.", ephemeral=True)
        return False

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.delete_profile(interaction, self.user_id)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(content="Domme profile deletion cancelled.", view=None)
        self.stop()

    async def on_timeout(self) -> None:
        _disable_all(self)
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class DommeNameModal(discord.ui.Modal, title="Name + Honorific"):
    def __init__(self, service: DommeProfileService, session: DommeProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

        self.name_input = discord.ui.TextInput(
            label="Name",
            default=session.name or "",
            required=False,
            max_length=100,
        )
        self.honorific_input = discord.ui.TextInput(
            label="Honorific (comma separated)",
            default=session.honorific or "",
            required=False,
            max_length=200,
        )
        self.add_item(self.name_input)
        self.add_item(self.honorific_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.session.name = _clean_optional(self.name_input.value)
        self.session.honorific = _clean_optional(self.honorific_input.value)
        await interaction.response.defer()
        await self.service.show_details_step(self.session, interaction)


class DommeDetailsModal(discord.ui.Modal, title="The Nitty Gritty"):
    def __init__(self, service: DommeProfileService, session: DommeProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

        self.pronouns_input = discord.ui.TextInput(
            label="Pronouns",
            default=session.pronouns or "",
            required=False,
            max_length=100,
        )
        self.age_input = discord.ui.TextInput(
            label="Age",
            default=session.age or "",
            required=False,
            max_length=50,
        )
        self.tribute_price_input = discord.ui.TextInput(
            label="Tribute Fee Price",
            default=session.tribute_price or "",
            required=False,
            max_length=100,
        )
        self.kinks_input = discord.ui.TextInput(
            label="Kinks",
            default=session.kinks or "",
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.limits_input = discord.ui.TextInput(
            label="Limits",
            default=session.limits or "",
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
        )
        self.add_item(self.pronouns_input)
        self.add_item(self.age_input)
        self.add_item(self.tribute_price_input)
        self.add_item(self.kinks_input)
        self.add_item(self.limits_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.session.pronouns = _clean_optional(self.pronouns_input.value)
        self.session.age = _clean_optional(self.age_input.value)
        self.session.tribute_price = _clean_optional(self.tribute_price_input.value)
        self.session.kinks = _clean_optional(self.kinks_input.value)
        self.session.limits = _clean_optional(self.limits_input.value)
        await interaction.response.defer()
        await self.service.show_payments_step(self.session, interaction)


class DommeThroneLinksModal(discord.ui.Modal, title="Throne & Tribute"):
    def __init__(self, service: DommeProfileService, session: DommeProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

        self.throne_input = discord.ui.TextInput(
            label="Throne URL",
            default=session.throne or "",
            required=False,
            max_length=200,
            placeholder="https://throne.com/yourname",
        )
        self.tribute_input = discord.ui.TextInput(
            label="Preferred Tribute Link",
            default=session.tribute_link or "",
            required=False,
            max_length=200,
            placeholder="Your main tribute link — shown as a button on your profile",
        )
        self.add_item(self.throne_input)
        self.add_item(self.tribute_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.session.throne = _clean_optional(self.throne_input.value)
        self.session.tribute_link = _clean_optional(self.tribute_input.value)
        await interaction.response.defer()
        await self.service.refresh_payments_step(self.session, interaction)


class DommePaymentLinksModal(discord.ui.Modal, title="Payment Links"):
    def __init__(self, service: DommeProfileService, session: DommeProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

        self.link1_input = discord.ui.TextInput(
            label="Payment Link 1 (e.g. PayPal, CashApp…)",
            default=session.payment_link1 or "",
            required=False,
            max_length=200,
        )
        self.link2_input = discord.ui.TextInput(
            label="Payment Link 2",
            default=session.payment_link2 or "",
            required=False,
            max_length=200,
        )
        self.link3_input = discord.ui.TextInput(
            label="Payment Link 3",
            default=session.payment_link3 or "",
            required=False,
            max_length=200,
        )
        self.link4_input = discord.ui.TextInput(
            label="Payment Link 4",
            default=session.payment_link4 or "",
            required=False,
            max_length=200,
        )
        self.add_item(self.link1_input)
        self.add_item(self.link2_input)
        self.add_item(self.link3_input)
        self.add_item(self.link4_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.session.payment_link1 = _clean_optional(self.link1_input.value)
        self.session.payment_link2 = _clean_optional(self.link2_input.value)
        self.session.payment_link3 = _clean_optional(self.link3_input.value)
        self.session.payment_link4 = _clean_optional(self.link4_input.value)
        await interaction.response.defer()
        await self.service.refresh_payments_step(self.session, interaction)


class DommeContentLinksModal(discord.ui.Modal, title="Content Links"):
    def __init__(self, service: DommeProfileService, session: DommeProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

        self.link1_input = discord.ui.TextInput(
            label="Content Link 1 (e.g. OnlyFans, Fansly…)",
            default=session.content_link1 or "",
            required=False,
            max_length=200,
        )
        self.link2_input = discord.ui.TextInput(
            label="Content Link 2",
            default=session.content_link2 or "",
            required=False,
            max_length=200,
        )
        self.link3_input = discord.ui.TextInput(
            label="Content Link 3",
            default=session.content_link3 or "",
            required=False,
            max_length=200,
        )
        self.link4_input = discord.ui.TextInput(
            label="Content Link 4",
            default=session.content_link4 or "",
            required=False,
            max_length=200,
        )
        self.add_item(self.link1_input)
        self.add_item(self.link2_input)
        self.add_item(self.link3_input)
        self.add_item(self.link4_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.session.content_link1 = _clean_optional(self.link1_input.value)
        self.session.content_link2 = _clean_optional(self.link2_input.value)
        self.session.content_link3 = _clean_optional(self.link3_input.value)
        self.session.content_link4 = _clean_optional(self.link4_input.value)
        await interaction.response.defer()
        await self.service.refresh_payments_step(self.session, interaction)


# ---------------------------------------------------------------------------
# Sub profile setup views and modals
# ---------------------------------------------------------------------------

class SubSetupView(discord.ui.View):
    def __init__(self, service: SubProfileService, session: SubProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.session.user_id:
            return True
        await interaction.response.send_message("This setup is not for you.", ephemeral=True)
        return False

    async def on_timeout(self) -> None:
        if self.session.current_view is not self:
            return
        _disable_all(self)
        if self.session.message:
            try:
                await self.session.message.edit(view=self)
            except discord.HTTPException:
                pass
        self.session.current_view = None
        self.service.finish_session(self.session.user_id)


class SubSetupIntroView(SubSetupView):
    @discord.ui.button(label="Continue", style=discord.ButtonStyle.primary)
    async def continue_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_name_step(self.session, interaction)

    @discord.ui.button(label="Later", style=discord.ButtonStyle.secondary)
    async def later_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        self.service.finish_session(self.session.user_id)
        await interaction.response.edit_message(
            embed=self.service.build_later_embed(),
            view=None,
        )
        self.stop()


class SubSetupNameView(SubSetupView):
    @discord.ui.button(label="Set Throne Name", style=discord.ButtonStyle.primary)
    async def set_name_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(SubThroneNameModal(self.service, self.session))

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_details_step(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_intro_step(self.session, interaction)


class SubSetupReviewView(SubSetupView):
    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def confirm_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.save_profile(self.session, interaction)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        self.service.finish_session(self.session.user_id)
        await interaction.response.edit_message(
            embed=self.service.build_cancelled_embed(),
            view=None,
        )
        self.stop()

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_owner_step(self.session, interaction)


class SubDeleteConfirmView(discord.ui.View):
    def __init__(self, service: SubProfileService, user_id: int) -> None:
        super().__init__(timeout=120)
        self.service = service
        self.user_id = user_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.user_id:
            return True
        await interaction.response.send_message("This confirmation is not for you.", ephemeral=True)
        return False

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.delete_profile(interaction, self.user_id)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.edit_message(content="Sub profile deletion cancelled.", view=None)
        self.stop()

    async def on_timeout(self) -> None:
        _disable_all(self)
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class SubThroneNameModal(discord.ui.Modal, title="Throne Name"):
    def __init__(self, service: SubProfileService, session: SubProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

        self.throne_name_input = discord.ui.TextInput(
            label="Your Throne sending name",
            default=session.throne_name or "",
            required=False,
            max_length=100,
            placeholder="The name shown when you send on Throne",
        )
        self.add_item(self.throne_name_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.session.throne_name = _clean_optional(self.throne_name_input.value)
        await interaction.response.defer()
        await self.service.show_details_step(self.session, interaction)


class SubSetupDetailsView(SubSetupView):
    @discord.ui.button(label="Add Details", style=discord.ButtonStyle.primary)
    async def open_modal(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(SubDetailsModal(self.service, self.session))

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_kinks_limits_step(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_name_step(self.session, interaction)


class SubDetailsModal(discord.ui.Modal, title="Personal Details"):
    def __init__(self, service: SubProfileService, session: SubProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

        self.name_input = discord.ui.TextInput(
            label="Name",
            default=session.name or "",
            required=False,
            max_length=100,
        )
        self.pronouns_input = discord.ui.TextInput(
            label="Pronouns",
            default=session.pronouns or "",
            required=False,
            max_length=100,
        )
        self.age_input = discord.ui.TextInput(
            label="Age",
            default=session.age or "",
            required=False,
            max_length=50,
        )
        self.add_item(self.name_input)
        self.add_item(self.pronouns_input)
        self.add_item(self.age_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.session.name = _clean_optional(self.name_input.value)
        self.session.pronouns = _clean_optional(self.pronouns_input.value)
        self.session.age = _clean_optional(self.age_input.value)
        await interaction.response.defer()
        await self.service.show_kinks_limits_step(self.session, interaction)


class SubSetupKinksLimitsView(SubSetupView):
    @discord.ui.button(label="Add Kinks & Limits", style=discord.ButtonStyle.primary)
    async def open_modal(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await interaction.response.send_modal(SubKinksLimitsModal(self.service, self.session))

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_color_step(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_details_step(self.session, interaction)


class SubKinksLimitsModal(discord.ui.Modal, title="Kinks & Limits"):
    def __init__(self, service: SubProfileService, session: SubProfileSession) -> None:
        super().__init__(timeout=900)
        self.service = service
        self.session = session

        self.kinks_input = discord.ui.TextInput(
            label="Kinks",
            default=session.kinks or "",
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
            placeholder="Things you enjoy…",
        )
        self.limits_input = discord.ui.TextInput(
            label="Limits",
            default=session.limits or "",
            required=False,
            max_length=500,
            style=discord.TextStyle.paragraph,
            placeholder="Hard limits or things to avoid…",
        )
        self.add_item(self.kinks_input)
        self.add_item(self.limits_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        self.session.kinks = _clean_optional(self.kinks_input.value)
        self.session.limits = _clean_optional(self.limits_input.value)
        await interaction.response.defer()
        await self.service.show_color_step(self.session, interaction)


class SubSetupColorView(SubSetupView):
    @discord.ui.select(
        placeholder="Choose a profile colour…",
        options=[
            discord.SelectOption(label=label, value=str(value), emoji=emoji)
            for value, emoji, label in PROFILE_COLOR_PRESETS
        ],
    )
    async def color_select(
        self,
        interaction: discord.Interaction,
        select: discord.ui.Select,
    ) -> None:
        self.session.profile_color = int(select.values[0])
        await self.service.show_color_step(self.session, interaction)

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def continue_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_owner_step(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_kinks_limits_step(self.session, interaction)


class _OwnerSelect(discord.ui.Select["SubSetupOwnerView"]):
    def __init__(self, options: list[discord.SelectOption]) -> None:
        super().__init__(placeholder="Choose a Domme (or None)…", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.values[0]
        self.view.session.owned_by_domme_user_id = None if value == "none" else int(value)
        await self.view.service.refresh_owner_step(self.view.session, interaction, self.options)


class SubSetupOwnerView(SubSetupView):
    def __init__(
        self,
        service: SubProfileService,
        session: SubProfileSession,
        options: list[discord.SelectOption],
    ) -> None:
        super().__init__(service, session)
        self.add_item(_OwnerSelect(options))

    @discord.ui.button(label="Continue", style=discord.ButtonStyle.success)
    async def continue_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_review_step(self.session, interaction)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary)
    async def skip_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        self.session.owned_by_domme_user_id = None
        await self.service.show_review_step(self.session, interaction)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def back_button(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        await self.service.show_color_step(self.session, interaction)
