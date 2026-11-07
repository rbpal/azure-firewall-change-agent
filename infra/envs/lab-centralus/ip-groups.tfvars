# Synthetic network data. All names and addresses are fictional.
ip_groups = {
  ipg-sett-lab-dr = {
    name  = "ipg-sett-lab-dr"
    cidrs = ["10.107.14.0/24"]
  }
  ipg-ledg-lab-dr = {
    name  = "ipg-ledg-lab-dr"
    cidrs = ["10.107.16.0/24"]
  }
  ipg-xfer-lab-dr = {
    name  = "ipg-xfer-lab-dr"
    cidrs = ["10.107.20.0/24"]
  }
  # Rules and tickets use the key. The Azure name adds -dr: the primary site
  # already has an IP group with the key's name in the same resource group.
  ipg-onprem-primary = {
    name  = "ipg-onprem-primary-dr"
    cidrs = ["172.20.10.0/23", "172.20.12.0/23", "172.20.14.0/24", "172.20.16.0/24", "172.20.20.0/24", "172.20.64.0/22", "172.20.68.0/23", "172.20.96.0/24"]
  }
  ipg-onprem-secondary = {
    name  = "ipg-onprem-secondary-dr"
    cidrs = ["172.24.10.0/23", "172.24.12.0/24", "172.24.14.0/24", "172.24.64.0/22", "172.24.96.0/24"]
  }
}
