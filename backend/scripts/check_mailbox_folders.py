"""List Graph folders and recent messages (diagnostic)."""
from app.services.email_ingestion import _mailbox_path
from app.services.graph_client import graph_request, is_graph_enabled


def main() -> None:
    if not is_graph_enabled():
        print("Graph not configured")
        return

    children = graph_request("GET", _mailbox_path("/mailFolders/inbox/childFolders"))
    print("=== Inbox child folders ===")
    processed_id = None
    for folder in children.get("value", []):
        name = folder.get("displayName")
        total = folder.get("totalItemCount")
        fid = folder.get("id", "")
        print(f"  {name}: messages={total}")
        if name == "Processed":
            processed_id = fid

    top = graph_request("GET", _mailbox_path("/mailFolders"))
    print("=== Top-level folders ===")
    for folder in top.get("value", []):
        print(f"  {folder.get('displayName')}: messages={folder.get('totalItemCount')}")

    if processed_id:
        msgs = graph_request(
            "GET",
            _mailbox_path(f"/mailFolders/{processed_id}/messages"),
            params={"$top": "10", "$select": "subject,receivedDateTime,isRead"},
        )
        print("=== Messages in Processed ===")
        for msg in msgs.get("value", []):
            print(f"  {msg.get('receivedDateTime')} | {msg.get('subject')}")
    else:
        print("Processed folder NOT found under Inbox via API")

    inbox = graph_request(
        "GET",
        _mailbox_path("/mailFolders/inbox/messages"),
        params={
            "$top": "10",
            "$select": "subject,receivedDateTime,isRead",
        },
    )
    print("=== Recent Inbox (may include read) ===")
    for msg in inbox.get("value", []):
        read = msg.get("isRead")
        print(f"  {msg.get('receivedDateTime')} | read={read} | {msg.get('subject')}")


if __name__ == "__main__":
    main()
