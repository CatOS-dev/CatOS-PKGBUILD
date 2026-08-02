# catos-limine-theme

CatOS visual theme for the Limine boot menu.

The package installs the source theme under `/usr/share/limine/themes/catos`.
`catos-limine-theme apply` copies the firmware-readable assets to the active
EFI System Partition and atomically replaces only the managed theme block in
`limine.conf`. Existing boot entries and unrelated global settings are left
unchanged.
