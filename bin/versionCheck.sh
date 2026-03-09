#!/usr/bin/env bash

set -e # halt script on error
set -x # print debugging

TARGET_BRANCH=$1
IS_PULL_REQUEST=$2  # false if not a pull request,

# Makes sure travis does not check version if doing a pull request
if [ "$IS_PULL_REQUEST" != "false" ]; then
    if git diff --quiet "origin/${TARGET_BRANCH}...HEAD" 'terrawrap' "test" "bin" setup.* ./*.pip; then
        echo "No changes found to main code or dependencies: no version change needed"
        exit 0
    fi

    CURRENT_VERSION=$(git show "origin/${TARGET_BRANCH}:terrawrap/version.py" | sed -n 's/^__version__ = "\(.*\)"$/\1/p')
    NEW_VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' terrawrap/version.py)

    if [ "$CURRENT_VERSION" == "$NEW_VERSION" ]; then
        FAILURE_REASON="Failure reason: Version number should be bumped."
    fi

    if ! python3 -c "from packaging.version import parse; exit(0 if parse('$NEW_VERSION') > parse('$CURRENT_VERSION') else 1)"; then
        FAILURE_REASON="Failure Reason: New version ($NEW_VERSION) is not greater than current version ($CURRENT_VERSION)"
    fi


    if [ -n "$FAILURE_REASON" ]; then
        set +x # is super annoying
        echo "============== PR Build Failed ==================="
        echo
        echo "$FAILURE_REASON"
        echo
        echo "=================================================="
        exit 1
    fi
fi
