if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "Error: This script must be sourced. Run: source $0"
    exit 1
fi

aws login --profile management --region eu-central-2
export AWS_PROFILE=workload
aws sts get-caller-identity