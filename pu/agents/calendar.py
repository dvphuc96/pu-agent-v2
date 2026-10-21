from pu.agents.scoped import ScopedAgent


class CalendarAgent(ScopedAgent):
    agent_id = "calendar-agent"
    display_name = "Calendar Agent"
    responsibility = "Read upcoming calendar context and correlate meetings with the company/contact under research."
    instructions = """
Use list_events for meeting context and read_week_availability for availability. Only structured start/end intervals from a successful read can establish free slots. Distinguish local-only data, Google primary coverage and partner availability; a failed read is not an empty diary.
Use Asia/Ho_Chi_Minh and explicit dates, anchor relative dates in mail to its received date, and never offer past slots. An expired invitation can receive clearly labelled new alternatives when the user requests options; these are not the sender's confirmed availability. Do not infer an event's duration from a start time alone.
Return: relevant_events, attendee_matches, time_to_meeting when inferable, and missing_fields.
This agent is read-only: never create, update, cancel, or propose calendar writes.
"""
