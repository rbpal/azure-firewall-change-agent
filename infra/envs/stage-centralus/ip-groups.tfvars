# Synthetic network data. All names and addresses are fictional.
ip_groups = {
  ipg-sett-stage-dr = {
    name  = "ipg-sett-stage-dr"
    cidrs = ["10.103.14.0/24"]
  }
  ipg-rprt-stage-dr = {
    name  = "ipg-rprt-stage-dr"
    cidrs = ["10.103.15.0/24"]
  }
  ipg-ledg-stage-dr = {
    name  = "ipg-ledg-stage-dr"
    cidrs = ["10.103.16.0/24"]
  }
  ipg-port-stage-dr = {
    name  = "ipg-port-stage-dr"
    cidrs = ["10.103.17.0/24"]
  }
  ipg-xfer-stage-dr = {
    name  = "ipg-xfer-stage-dr"
    cidrs = ["10.103.20.0/24"]
  }
  ipg-onprem-primary = {
    name  = "ipg-onprem-primary"
    cidrs = ["172.20.10.0/23", "172.20.12.0/23", "172.20.14.0/24", "172.20.16.0/24", "172.20.20.0/24", "172.20.64.0/22", "172.20.68.0/23", "172.20.96.0/24"]
  }
  ipg-onprem-secondary = {
    name  = "ipg-onprem-secondary"
    cidrs = ["172.24.10.0/23", "172.24.12.0/24", "172.24.14.0/24", "172.24.64.0/22", "172.24.96.0/24"]
  }
}
