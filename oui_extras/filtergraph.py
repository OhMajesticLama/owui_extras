import time
from typing import (
    Optional,
    Callable,
    Any,
    Awaitable,
    Dict,
)
import pprint

from pydantic import BaseModel, Field
import langgraph.graph

import open_webui  # type: ignore
from open_webui.env import GLOBAL_LOG_LEVEL  # type: ignore


from open_webui.socket.main import get_event_emitter  # type: ignore

from oui_extras.logs import set_logs, log_exceptions
from oui_extras.messages import get_last_message
from oui_extras.constants import LOGGER, ROLE
from oui_extras.context import add_or_update_filter_context


# from open_webui.main import webui_app

set_logs(LOGGER, GLOBAL_LOG_LEVEL)
# /!\ Do not leave DEBUG mode on: conversation content will leak in logs.
# set_logs(LOGGER, logging.DEBUG)


class FilterGraph:
    class Valves(BaseModel):
        priority: int = Field(
            default=0,
            description=(
                "Higher priority means this will be executed after lower priority functions."
                "This is a basic context input, put it ahead of higher-level reasoning."
            ),
        )
        model: str = Field(
            default="artifish/llama3.2-uncensored:latest",
            description=("Model to use for emotion assessment."),
        )

    class UserValves(BaseModel):
        enabled: bool = Field(
            default=True, description="Enable or disable the time awareness function."
        )

    def __init__(
        self,
        graph: langgraph.graph.Graph,
        context_id: str,
        register_context: bool = False,
    ):
        """

        Example use:
            >>> class Filter(FilterGraph):
            ...     class State(TypedDict):
            ...         body: Dict[str, ...]
            ...         __user__: Dict[str, ...]
            ...         __event_emitter__: Callable[[...], Any]
            ...         Afoo: str
            ...
            ...     def __init__(self):
            ...         START = langgraph.graph.START
            ...         END = langgraph.graph.END
            ...
            ...         stategraph = langgraph.graph.StateGraph(self.State)
            ...
            ...         async def _A(msg):
            ...             return {**msg, **{"Afoo": "bar"}}
            ...
            ...         async def _B(msg):
            ...             return {**msg, **{"Bfoo": "bar"}}
            ...
            ...         stategraph.add_node("A", _A)
            ...         stategraph.add_node("B", _B)
            ...
            ...         stategraph.add_edge(START, "A")
            ...         stategraph.add_edge("A", "B")
            ...         stategraph.add_edge("B", END)
            ...
            ...         graph = stategraph.compile()
            ...         super().__init__(graph=graph, context_id="POC_GRAPH")
            ...

        """
        # Indicates custom file handling logic. This flag helps disengage default routines in favor of custom
        # implementations, informing the WebUI to defer file-related operations to designated methods within this class.
        # Alternatively, you can remove the files directly from the body in from the inlet hook
        # self.file_handler = True

        # Initialize 'valves' with specific configurations. Using 'Valves' instance helps encapsulate settings,
        # which ensures settings are managed cohesively and not confused with operational flags like 'file_handler'.
        self.valves = self.Valves()
        self.uservalves = self.UserValves()
        self._queries: Dict[str, Dict[str, Any]] = {}
        self.register_context = register_context  # DEBUG: currently not used
        "Register context in last user message."

        self.register_query_timeout: int = 1800
        "Number of seconds before a query is considered timed-out and removed from local cache."

        self.graph = graph

        self.context_id = context_id
        "Used to identify and manage context from this filter. Should be different from other filters."

    @log_exceptions
    async def inlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
        __user__: Optional[dict] = None,
    ) -> dict:
        if __user__ is None:
            LOGGER.info("__user__ is None. Need user to query emotion model. Abort.")
            return body
        if not __user__["valves"].enabled:
            # user doesn't want this, do nothing.
            LOGGER.debug("UserValve.enabled = False. Do nothing.")
            return body
        if "id" not in __user__:
            LOGGER.warning("no 'id' key in __user__. do nothing.")
            return body

        LOGGER.debug(f"inlet:{__name__}")
        LOGGER.debug(f"inlet:body:\n{pprint.pformat(body)}")
        LOGGER.debug(f"inlet:user:{__user__}")

        graph_out = await self.graph.ainvoke(  # type: ignore # not in our control
            {
                "body": body,
                "__user__": __user__,
                "__event_emitter__": __event_emitter__,
            }
        )

        LOGGER.debug("inlet:graph_out: %s", pprint.pformat(graph_out))

        body = graph_out["body"]
        context = graph_out.get("context")

        messages: Optional[Dict[str, str]] = body.get("messages")
        if not messages:
            # nothing to do here.
            return body

        user_message, user_message_ind = get_last_message(messages, ROLE.USER)

        if user_message_ind is None or user_message is None:
            LOGGER.info("No message from user found. Do nothing.")
            return body

        if context:
            user_message["content"] = add_or_update_filter_context(
                user_message["content"],
                context,
                id=self.context_id,
            )

        if query_id := body.get("metadata", {}).get("message_id"):
            # Store it here, we'll set it in outlet.
            self._queries[query_id] = {
                "graph_response": graph_out,
                "timestamp": time.time(),
            }

        LOGGER.debug("inlet:out:body: %s", body)
        return body

    @log_exceptions
    async def outlet(
        self,
        body: dict,
        __event_emitter__: Callable[[Any], Awaitable[None]],
        __user__: Optional[dict] = None,
    ) -> dict:
        LOGGER.debug("outlet:body: %s", pprint.pformat(body))
        LOGGER.debug("outlet:user: %s", pprint.pformat(__user__))
        answer_id = body.get("id")
        session_id = body.get("session_id")
        chat_id = body.get("chat_id")
        messages = body.get("messages")
        if None in (answer_id, session_id, chat_id, messages, __user__):
            # nothing we can do, do nothing.
            LOGGER.debug(
                "oulet:Missing context information. Do nothing. user %s | body %s",
                __user__,
                body,
            )
            return body
        user_id = __user__.get("id")  # type: ignore # checked above

        # find last user message going up in parents
        user_msg, user_msg_ind = get_last_message(messages, ROLE.USER)
        # find query
        query = self._queries.get(answer_id)  # type:ignore # checked above.
        if query is None:
            # No query was registered with this id. Do nothing
            LOGGER.debug("query %s not found in %s", answer_id, self._queries)
            return body

        if context := query.get("context"):
            user_msg["content"] = add_or_update_filter_context(
                user_msg["content"], context, self.context_id
            )

            # Build event emitter and send message back
            user_msg_event_emitter = get_event_emitter(
                {
                    "chat_id": chat_id,
                    "message_id": user_msg.get("id"),
                    "session_id": session_id,
                    "user_id": user_id,
                }
            )

            # This is outlet, awaiting has little impact on UX, do it.
            await user_msg_event_emitter(
                {
                    "type": "replace",
                    "data": {
                        "content": user_msg["content"],
                    },
                }
            )
        # Clean-up potential old queries
        for k, v in self._queries.copy().items():
            if time.time() - v.get("timestamp", 0) > self.register_query_timeout:
                # Over 30 minutes have passed since query,
                # let's consider it timed-out.
                try:
                    del self._queries[k]
                except KeyError:
                    pass  # key has been deleted meanwhile, don't care.

        return body
