from droplet_sdk import DropletClient


def main() -> None:
    with DropletClient() as client:
        challenges = client.list_challenges()
        print("challenges:", challenges)
        challenge = next(item for item in challenges if item["status"] == "running")
        print("target:", challenge["target_url"])
        print("stats:", client.stats())


if __name__ == "__main__":
    main()
