#!/usr/bin/env bash
set -e

# Get the latest tag
LATEST_TAG=$(git tag --list 'v*' --sort=-version:refname | head -1)

if [ -z "$LATEST_TAG" ]; then
  echo "No existing version tags found. Starting with v1.0.0"
  LATEST_TAG="v0.0.0"
fi

echo "Current version: $LATEST_TAG"

# Parse version components (remove 'v' prefix)
VERSION="${LATEST_TAG#v}"
IFS='.' read -r MAJOR MINOR PATCH <<< "$VERSION"

# Default bump type
BUMP_TYPE="${1:-patch}"

case "$BUMP_TYPE" in
  major)
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    ;;
  minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    ;;
  patch)
    PATCH=$((PATCH + 1))
    ;;
  *)
    echo "Usage: $0 [major|minor|patch]"
    echo "  major: bump major version (X.0.0)"
    echo "  minor: bump minor version (x.Y.0)"
    echo "  patch: bump patch version (x.y.Z) [default]"
    exit 1
    ;;
esac

NEW_VERSION="v${MAJOR}.${MINOR}.${PATCH}"

echo "New version: $NEW_VERSION"
echo ""
read -p "Create tag $NEW_VERSION? [y/N] " -n 1 -r
echo

if [[ $REPLY =~ ^[Yy]$ ]]; then
  # Check if there are uncommitted changes
  if ! git diff-index --quiet HEAD --; then
    echo "Warning: You have uncommitted changes. Please commit them first."
    exit 1
  fi

  # Create annotated tag
  git tag -a "$NEW_VERSION" -m "Release $NEW_VERSION"
  echo "✓ Created tag $NEW_VERSION"

  # Push the tag to remote
  echo "Pushing tag to remote..."
  git push origin "$NEW_VERSION"
  echo "✓ Pushed tag $NEW_VERSION to remote"
else
  echo "Cancelled."
  exit 1
fi
