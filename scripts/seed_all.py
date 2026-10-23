"""Run all seed scripts: policies, resources, users.

Run: python -m scripts.seed_all
"""
from scripts.seed_policies import seed_policies
from scripts.seed_resources import seed_resources
from scripts.seed_users import seed_users


def main():
    print("=" * 60)
    print("Seeding policies...")
    seed_policies()
    print("\nSeeding resources...")
    seed_resources()
    print("\nSeeding users...")
    seed_users()
    print("=" * 60)
    print("All seeds complete!")


if __name__ == "__main__":
    main()
