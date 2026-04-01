# --- Variables ---
#COMPONENTS := dns dhcp
COMPONENTS       := dns dhcp oc-mirror execution-environment tftp
BOOTSTRAP_IMG    := localhost/bootstrap:latest
COMPONENT_IMGS        := $(foreach component,$(COMPONENTS),localhost/$(component):latest)

BUILD_TARGETS  := $(addprefix build-, $(COMPONENTS))
EXPORT_TARGETS := $(addprefix export-, $(COMPONENTS))

EXPORT_DIR     ?= ./images/bootstrap/overlay/usr/lib/container-images
BUILD_ARG_FILE ?= ./ignore/build-args.txt

KICKSTART	   ?= ./kickstarts/default.ks
RHEL_BOOT_ISO  ?= ./rhel-9.6-x86_64-boot.iso
BOOTSTRAP_ISO_OUTPUT_DIR ?= /tmp/install-bootstrap.iso

# --- Targets ---
.PHONY: all clean build-bootstrap build-all export-all create-boostrap-install-iso

all: build-bootstrap

$(EXPORT_DIR):
	mkdir -p $(EXPORT_DIR)

prep-base:
	@echo "==> Building base registered image..."
	podman build \
	--tag localhost/registered-base:latest \
	--build-arg-file $(BUILD_ARG_FILE) \
	./images/registered-base/

build-%: prep-base
	@echo "==> Building $* image..."
	podman build \
	--tag localhost/$*:latest \
	--build-arg-file $(BUILD_ARG_FILE) \
	./images/$*/

export-%: build-% | $(EXPORT_DIR)
	@echo "==> Exporting $* image..."
	podman save \
	--format oci-archive \
	--output $(EXPORT_DIR)/$*.tar \
	localhost/$*:latest

build-all: $(BUILD_TARGETS)
export-all: $(EXPORT_TARGETS)

build-bootstrap: export-all
	@echo "==> Building bootstrap image..."
	podman build \
	--tag localhost/bootstrap:latest \
	--build-arg-file $(BUILD_ARG_FILE) \
	./images/bootstrap/

create-bootstrap-install-iso: build-bootstrap
	@echo "==> Building installer ISO..."
	./scripts/create-iso.sh \
	localhost/bootstrap:latest \
	$(KICKSTART) \
	$(RHEL_BOOT_ISO) \
	"$(CURDIR)/install-bootstrap.iso"

clean:
	@echo "==> Cleaning up exports..."
	rm -rf $(EXPORT_DIR)/*.tar
	@echo "==> Deleting images..."
	podman rmi -f $(COMPONENT_IMGS) $(BOOTSTRAP_IMG) localhost/registered-base:latest
	@echo "==> Cleaning up ISO..."
	rm -f install-bootstrap.iso
