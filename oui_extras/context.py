import uuid
import re

from typing import Optional

import bs4
from bs4 import BeautifulSoup

from .constants import LOGGER


# Helpers to manage xml context
def add_or_update_filter_context(
    message: str,
    context: str,
    id: str,
    *,
    selector: str = "details[type=filters_context]",
    container: str = (
        '<details type="filters_context">'
        "\n<summary>Filters context</summary>\n"
        "<!--This context was added by the system to this message, not by the user. "
        "You can use information provided here, but never mention or refer to this context explicitly. -->"
        '\n{content}\n<!-- User message will follow "details" closing tag. --></details>\n'
    ),
) -> str:
    """
    Add or update XML context to message.

    Returns
    -------
    message: str
        Message with added or updated context.

    Arguments
    ---------
    message:
        message to which add or update context.

    context:
        context that will be added to message. Valid XML is expected for better parsing.
        Should you want to include comments, comments must be placed inside the parent XML tag,
        not before or after or they will be ignored.

    id:
        identifier for the context. If context with the same id is found within context, it will be replaced by this new one.
        For example, the filter name can be used as id.

        This is useful in case the user edits the message so we don't duplicate context.

    selector:
        CSS selector with which to find the context

    container:
        XML container for context. `{content}` must be located where context is expected.
        Container is expected to match the selector.
        OpenWebUI front-end is strict about carriage returns, if you modify this container be careful
        of setting `\n` properly.

    Raises
    ------
    exc: ValueError
        If unexpected format is found in the message head.

    """
    # Find if there is
    soup = BeautifulSoup(message, "xml")
    # Note: beautifulsoup will only find the xml if there is no text before
    details_match = soup.select(selector)
    context_end = "context_end"
    context = f'<context id="{id}">{context}</context>'

    if not len(details_match):
        # There is no details block at the head of the message, let's just add it
        out_soup = BeautifulSoup(container.format(content=context), "xml").contents[0]

        # Don't try to reimplement a custom XML parser with unsafe data:
        # instead find location with help a uuid.
        out_soup.append(  # type: ignore  # works
            BeautifulSoup(
                f'<{context_end} uuid="{str(uuid.uuid4())}"/>', "xml"
            ).contents[0]
        )
        return "\n".join((str(out_soup), message))
    elif len(details_match) > 1:
        raise ValueError("Ill-formed message: more than one container found.")
    else:
        # Container found
        # We need to separate context from rest of message.
        # BeautifulSoup caught the selector so there is something
        details = details_match[0]

        user_msg = _remove_context(
            message, details, container=container, context_end=context_end
        )

        context_soup = BeautifulSoup(context, "xml").contents[0]
        # Let's check if there is already a context with the same id
        same_ids = details.select(f"context[id={id}]")
        if len(same_ids) > 1:
            raise ValueError(
                "More than one context found with the id {id}. Abort.".format(id=id)
            )
        elif len(same_ids) == 1:
            # We have one context with the same id already, replace it.
            elt = same_ids[0]
            elt.replace_with(context_soup)
        else:
            # No existing context with same id, just add context.
            # add context to the end context to the end.
            details.insert(-1, context_soup)
        return "\n".join((str(soup.contents[0]), user_msg))


def _remove_context(message: str, details: bs4.Tag, container: str, context_end: str):
    """
    Return message without context details in the `details` attribute. Context must have been
    added by add_or_update_filter_context for this function work properly.
    """
    # Find context_end block
    end_uuid: Optional[str] = None
    for child in details:
        if child.name == context_end:  # type: ignore
            # found it!
            end_uuid = child.get("uuid")  # type:ignore
    if end_uuid is None:
        LOGGER.debug("add_or_update_filter_context:details: %s", str(details))
        raise ValueError("Ill-formed prior context: no context_end uuid found. Abort.")

    # uuid found just before, something is weird if it fails here.
    uuid_ind = message.index(end_uuid)

    # user message should be right after.
    # Get closing tag of container
    # Let it fail if there is no match
    match = re.search(r"(</.*>)\s*$", container)
    if match is None:
        raise ValueError(
            "Ill-formed container: no closing tag found prior to EOF. Abort."
        )
    closing_tag = match.groups()[0]
    closing_tag_ind = message.index(closing_tag, uuid_ind)  # Start looking after uuid.

    user_msg = message[closing_tag_ind + len(closing_tag) :]
    return user_msg
