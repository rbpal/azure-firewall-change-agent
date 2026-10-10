# infra

Terraform for the whole environment, plus the firewall rules as data.

## Build steps

Each step that creates Azure resources has its own numbered folder: `02-<name>/`, `03-<name>/`, and so on. Build them in number order. A folder never holds resources from a later step.

The first step is a one-time Azure CLI bootstrap. It creates the storage account that holds the Terraform state, because Terraform needs that account before it can run. It holds subscription details, so it is kept out of this repo.

Each numbered folder is its own Terraform root, with its own state file in the `tfstate` container (`02-rg.tfstate`, `03-network.tfstate`, and so on). A mistake in one step cannot change another step's resources. A later step finds an earlier step's resources by name.

Reusable code lives in `modules/`. A numbered folder calls modules and adds nothing else but the backend, the provider and its inputs.

Inside a numbered folder, names and values are kept apart:

| File | Holds |
| --- | --- |
| `variables.tf` | Variable names, types and descriptions. No values. Each block says which tfvars file sets it. |
| `<resource>.tfvars` | Values only, one file per resource, such as `rg.tfvars` and `budget.tfvars`. |
| `backend.tf` | Where this step's state file lives. |
| `providers.tf` | The `azurerm` provider settings. |
| `data.tf` | Existing resources the step reads but does not create, such as the resource group from an earlier step. |
| `main.tf` | The module calls. |
| `outputs.tf` | What later steps can read. |

## Running a step

The subscription ID is never written in this repo. Terraform reads it from your shell:

```bash
az login
export ARM_SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
cd infra/02-rg
terraform init
terraform plan -input=false -var-file=rg.tfvars -var-file=budget.tfvars -out=step.tfplan
terraform apply step.tfplan
```

Terraform loads only `terraform.tfvars` by itself, so each `<resource>.tfvars` file is passed with `-var-file`. With `-input=false`, a missing file makes `plan` stop and name the missing variable, instead of prompting for it.

Tear down in reverse order: the highest number first.

## Firewall rules

The rules are data in `envs/`, one folder per environment and site, such as `envs/dev-eastus2/`:

- `firewall_policy_rule_collection_groups/<spoke>.tfvars` holds one spoke's rule collection group. `hub.tfvars` holds the shared hub rules.
- `ip-groups.tfvars` holds the IP groups for that environment and site.
