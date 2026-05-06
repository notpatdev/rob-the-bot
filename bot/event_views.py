from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from bot.event_cog import RobEventCog


class RegistrationPanelView(discord.ui.View):
    def __init__(self, cog: RobEventCog) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Domme Sign Up",
        style=discord.ButtonStyle.primary,
        custom_id="rob:event:domme_signup",
    )
    async def domme_sign_up(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        reason = await self.cog.get_signup_block_reason(interaction, signup_type="domme")
        if reason is not None:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        await interaction.response.send_modal(DommeSignupModal(self.cog))

    @discord.ui.button(
        label="Sub Sign Up",
        style=discord.ButtonStyle.secondary,
        custom_id="rob:event:sub_signup",
    )
    async def sub_sign_up(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        reason = await self.cog.get_signup_block_reason(interaction, signup_type="sub")
        if reason is not None:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        await interaction.response.send_modal(SubSignupModal(self.cog))


class DommeSignupModal(discord.ui.Modal, title="Domme Sign Up"):
    def __init__(self, cog: RobEventCog) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.throne_value = discord.ui.TextInput(
            label="Throne Username or Link",
            placeholder="pattyboy03 or https://throne.com/pattyboy03",
            max_length=200,
        )
        self.add_item(self.throne_value)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.process_domme_signup(
            interaction,
            self.throne_value.value,
        )


class SubSignupModal(discord.ui.Modal, title="Sub Sign Up"):
    def __init__(self, cog: RobEventCog) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.sub_name = discord.ui.TextInput(
            label="Name to Track",
            placeholder="The name you'll use when sending on Throne",
            max_length=100,
        )
        self.add_item(self.sub_name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.process_sub_signup(
            interaction,
            self.sub_name.value,
        )


class EventStartPromptView(discord.ui.View):
    def __init__(self, cog: RobEventCog, *, owner_id: int) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.owner_id = owner_id

    @discord.ui.button(label="Set End Time", style=discord.ButtonStyle.primary)
    async def set_end_time(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who started this can use it.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(EventStartModal(self.cog))


class EventStartModal(discord.ui.Modal, title="Start Event"):
    def __init__(self, cog: RobEventCog) -> None:
        super().__init__(timeout=300)
        self.cog = cog
        self.end_date = discord.ui.TextInput(
            label="End Date",
            placeholder="YYYY-MM-DD",
            max_length=10,
        )
        self.end_time = discord.ui.TextInput(
            label="End Time",
            placeholder="HH:MM (24 hour)",
            max_length=5,
        )
        self.add_item(self.end_date)
        self.add_item(self.end_time)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.process_event_start_modal(
            interaction,
            end_date=self.end_date.value,
            end_time=self.end_time.value,
        )


class EventEndConfirmView(discord.ui.View):
    def __init__(self, cog: RobEventCog, *, owner_id: int) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.owner_id = owner_id

    @discord.ui.button(label="End Event", style=discord.ButtonStyle.danger)
    async def end_event(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who started this can use it.",
                ephemeral=True,
            )
            return
        await self.cog.process_event_end(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        _: discord.ui.Button,
    ) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Only the person who started this can use it.",
                ephemeral=True,
            )
            return
        self.stop()
        await interaction.response.edit_message(
            content="Event end cancelled.",
            embed=None,
            view=None,
        )


class SubLeaderboardView(discord.ui.View):
    def __init__(self, cog: RobEventCog, *, page: int = 0) -> None:
        super().__init__(timeout=900)
        self.cog = cog
        self.page = page
        self.previous_button = discord.ui.Button(label="<", style=discord.ButtonStyle.secondary)
        self.previous_button.callback = self._previous
        self.add_item(self.previous_button)
        self.page_button = discord.ui.Button(label="Page 1/1", style=discord.ButtonStyle.secondary, disabled=True)
        self.add_item(self.page_button)
        self.next_button = discord.ui.Button(label=">", style=discord.ButtonStyle.secondary)
        self.next_button.callback = self._next
        self.add_item(self.next_button)

    async def on_timeout(self) -> None:
        for item in self.children:
            if hasattr(item, "disabled"):
                item.disabled = True

    async def refresh(self, interaction: discord.Interaction) -> None:
        embed, total_pages = await self.cog.build_sub_leaderboard_page(self.page)
        self.previous_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= total_pages - 1
        self.page_button.label = f"Page {self.page + 1}/{max(total_pages, 1)}"
        await interaction.response.edit_message(embed=embed, view=self)

    async def _previous(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    async def _next(self, interaction: discord.Interaction) -> None:
        _, total_pages = await self.cog.build_sub_leaderboard_page(self.page)
        self.page = min(max(total_pages - 1, 0), self.page + 1)
        await self.refresh(interaction)
