from aiogram.fsm.state import State, StatesGroup


class NewTicket(StatesGroup):
    waiting_message = State()


class UserReply(StatesGroup):
    waiting_message = State()
