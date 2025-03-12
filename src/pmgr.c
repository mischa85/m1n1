/* SPDX-License-Identifier: MIT */

#include "pmgr.h"
#include "adt.h"
#include "string.h"
#include "types.h"
#include "utils.h"

#define PMGR_RESET        BIT(31)
#define PMGR_AUTO_ENABLE  BIT(28)
#define PMGR_PS_AUTO      GENMASK(27, 24)
#define PMGR_PARENT_OFF   BIT(11)
#define PMGR_DEV_DISABLE  BIT(10)
#define PMGR_WAS_CLKGATED BIT(9)
#define PMGR_WAS_PWRGATED BIT(8)
#define PMGR_PS_ACTUAL    GENMASK(7, 4)
#define PMGR_PS_TARGET    GENMASK(3, 0)

#define PMGR_POLL_TIMEOUT 10000

#define PMGR_FLAG_VIRTUAL 0x10

struct pmgr_device {
    u8 flags;
    u8 unk3_1;
    u8 unk3_2;
    u8 id1;
    union {
        struct {
            u8 parent[2];
            u8 unk2[2];
        } u8id;
        struct {
            u16 parent[2];
        } u16id;
    };
    u8 unk3[2];
    u8 addr_offset;
    u8 psreg_idx;
    u32 unk1;
    u32 unk2;
    u8 unk4[5];
    u8 unk3_3;
    u16 id2;
    u8 unk5[4];
    const char name[0x10];
} PACKED;

struct ps_regs {
    u32 reg;
    u32 offset;
    u32 mask;
} PACKED;

static int pmgr_initialized = 0;

static int pmgr_path[8];
static int pmgr_offset;
static int pmgr_dies;

static const u32 *pmgr_ps_regs = NULL;
static u32 pmgr_ps_regs_len = 0;

static const struct pmgr_device *pmgr_devices = NULL;
static u32 pmgr_devices_len = 0;

static bool pmgr_u8id = false;

static uintptr_t pmgr_get_psreg(u8 idx)
{
    if (idx * 12 >= pmgr_ps_regs_len) {
        printf("pmgr: Index %d is out of bounds for ps-regs\n", idx);
        return 0;
    }

    u32 reg_idx = pmgr_ps_regs[3 * idx];
    u32 reg_offset = pmgr_ps_regs[3 * idx + 1];

    u64 pmgr_reg;
    if (adt_get_reg(adt, pmgr_path, "reg", reg_idx, &pmgr_reg, NULL) < 0) {
        printf("pmgr: Error getting /arm-io/pmgr regs\n");
        return 0;
    }

    return pmgr_reg + reg_offset;
}

int pmgr_set_mode(uintptr_t addr, u8 target_mode)
{
    printf("pmgr: setting mode %x for device at 0x%lx: %x\n", target_mode,
        addr, read32(addr));
    mdelay(100);
    mask32(addr, PMGR_PS_TARGET, FIELD_PREP(PMGR_PS_TARGET, target_mode));
    if (poll32(addr, PMGR_PS_ACTUAL, FIELD_PREP(PMGR_PS_ACTUAL, target_mode), PMGR_POLL_TIMEOUT) <
        0) {
        printf("pmgr: timeout while trying to set mode %x for device at 0x%lx: %x\n", target_mode,
               addr, read32(addr));
        return -1;
    }

    return 0;
}

static u16 pmgr_adt_get_id(const struct pmgr_device *device)
{
    if (pmgr_u8id)
        return device->id1;
    else
        return device->id2;
}

static int pmgr_find_device(u16 id, const struct pmgr_device **device)
{
    for (size_t i = 0; i < pmgr_devices_len; ++i) {
        const struct pmgr_device *i_device = &pmgr_devices[i];
        if (pmgr_adt_get_id(i_device) != id)
            continue;

        *device = i_device;
        return 0;
    }

    return -1;
}

static uintptr_t pmgr_device_get_addr(u8 die, const struct pmgr_device *device)
{
#if TARGET == T6041
    u8 addr_offset;
    uintptr_t addr;
    if (strcmp(device->name, "ATC0_USB_AON") == 0) {
        printf("pmgr: ATC0_USB_AON\n");
        addr = pmgr_get_psreg(6);
        addr_offset = 0;
    } else if (strcmp(device->name, "ATC1_USB_AON") == 0) {
        printf("pmgr: ATC1_USB_AON\n");
        addr = pmgr_get_psreg(7);
        addr_offset = 0;
    } else if (strcmp(device->name, "ATC2_USB_AON") == 0) {
        printf("pmgr: ATC2_USB_AON\n");
        addr = pmgr_get_psreg(7);
        addr_offset = 0;
    } else if (strcmp(device->name, "ATC3_USB_AON") == 0) {
        printf("pmgr: ATC3_USB_AON\n");
        addr = pmgr_get_psreg(7);
        addr_offset = 0;
    } else if (strcmp(device->name, "ATC0_COMMON") == 0) {
        printf("pmgr: ATC0_COMMON\n");
        addr = pmgr_get_psreg(11);
        addr_offset = 9;
    } else if (strcmp(device->name, "ATC0_COMMON_DP") == 0) {
        printf("pmgr: ATC0_COMMON_DP\n");
        addr = pmgr_get_psreg(7);
        addr_offset = 0;
    } else if (strcmp(device->name, "ATC1_COMMON") == 0) {
        printf("pmgr: ATC1_COMMON\n");
        addr = pmgr_get_psreg(16);
        addr_offset = 9;
    } else if (strcmp(device->name, "ATC1_COMMON_DP") == 0) {
        printf("pmgr: ATC1_COMMON_DP\n");
        addr = pmgr_get_psreg(0);
        addr_offset = 0;
    } else if (strcmp(device->name, "ATC2_COMMON_DP") == 0) {
        printf("pmgr: ATC2_COMMON_DP\n");
        addr = pmgr_get_psreg(0);
        addr_offset = 0;
    } else if (strcmp(device->name, "ATC3_COMMON_DP") == 0) {
        printf("pmgr: ATC3_COMMON_DP\n");
        addr = pmgr_get_psreg(0);
        addr_offset = 0;
    } else if (strcmp(device->name, "FAB2_SOC") == 0) {
        printf("pmgr: FAB2_SOC\n");
        addr = pmgr_get_psreg(1);
        addr_offset = 0;
    } else if (strcmp(device->name, "AFI") == 0) {
        printf("pmgr: AFI\n");
        addr = pmgr_get_psreg(2);
        addr_offset = 0;
    } else {
        printf("pmgr: else...\n");
        addr = pmgr_get_psreg(0);
        addr_offset = 0;
    }
#else
    uintptr_t addr = pmgr_get_psreg(device->psreg_idx);
#endif
    if (addr == 0)
        return 0;

    addr += PMGR_DIE_OFFSET * die;

#if TARGET == T6041
    addr += (addr_offset << 3);
#else
    addr += (device->addr_offset << 3);
#endif
    return addr;
}

static void pmgr_adt_get_parents(const struct pmgr_device *device, u16 parent[2])
{
    if (pmgr_u8id) {
        parent[0] = device->u8id.parent[0];
        parent[1] = device->u8id.parent[1];
    } else {
        parent[0] = device->u16id.parent[0];
        parent[1] = device->u16id.parent[1];
    }
}

static int pmgr_set_mode_recursive(u8 die, u16 id, u8 target_mode, bool recurse)
{
    if (!pmgr_initialized) {
        printf("pmgr: pmgr_set_mode_recursive() called before successful pmgr_init()\n");
        return -1;
    }

    if (id == 0)
        return -1;

    const struct pmgr_device *device;

    if (pmgr_find_device(id, &device))
        return -1;

    if (target_mode == 0 && !(device->flags & PMGR_FLAG_VIRTUAL)) {
        uintptr_t addr = pmgr_device_get_addr(die, device);
        if (!addr)
            return -1;
        if (pmgr_set_mode(addr, target_mode))
            return -1;
    }

    if (recurse)
        for (int i = 0; i < 2; i++) {
            u16 parents[2];
            pmgr_adt_get_parents(device, parents);
            if (parents[i]) {
                int ret = pmgr_set_mode_recursive(die, parents[i], target_mode, true);
                if (ret < 0)
                    return ret;
            }
        }

    if (target_mode != 0 && !(device->flags & PMGR_FLAG_VIRTUAL)) {
        uintptr_t addr = pmgr_device_get_addr(die, device);
        if (!addr)
            return -1;
        if (pmgr_set_mode(addr, target_mode))
            return -1;
    }

    return 0;
}

int pmgr_power_enable(u32 id)
{
    u16 device = FIELD_GET(PMGR_DEVICE_ID, id);
    u8 die = FIELD_GET(PMGR_DIE_ID, id);
    return pmgr_set_mode_recursive(die, device, PMGR_PS_ACTIVE, true);
}

int pmgr_power_disable(u32 id)
{
    u16 device = FIELD_GET(PMGR_DEVICE_ID, id);
    u8 die = FIELD_GET(PMGR_DIE_ID, id);
    return pmgr_set_mode_recursive(die, device, PMGR_PS_PWRGATE, false);
}

static int pmgr_adt_find_devices(const char *path, const u32 **devices, u32 *n_devices)
{
    int node_offset = adt_path_offset(adt, path);
    if (node_offset < 0) {
        printf("pmgr: Error getting node %s\n", path);
        return -1;
    }

    *devices = adt_getprop(adt, node_offset, "clock-gates", n_devices);
    if (*devices == NULL || *n_devices == 0) {
        printf("pmgr: Error getting %s clock-gates.\n", path);
        return -1;
    }

    *n_devices /= 4;

    return 0;
}

static int pmgr_adt_devices_set_mode(const char *path, u8 target_mode, int recurse)
{
    const u32 *devices;
    u32 n_devices;
    int ret = 0;

    if (pmgr_adt_find_devices(path, &devices, &n_devices) < 0)
        return -1;

    for (u32 i = 0; i < n_devices; ++i) {
        u16 device = FIELD_GET(PMGR_DEVICE_ID, devices[i]);
        u8 die = FIELD_GET(PMGR_DIE_ID, devices[i]);
        if (pmgr_set_mode_recursive(die, device, target_mode, recurse))
            ret = -1;
    }

    return ret;
}

static int pmgr_adt_device_set_mode(const char *path, u32 index, u8 target_mode, int recurse)
{
    const u32 *devices;
    u32 n_devices;
    int ret = 0;

    if (pmgr_adt_find_devices(path, &devices, &n_devices) < 0)
        return -1;

    if (index >= n_devices)
        return -1;

    u16 device = FIELD_GET(PMGR_DEVICE_ID, devices[index]);
    u8 die = FIELD_GET(PMGR_DIE_ID, devices[index]);
    if (pmgr_set_mode_recursive(die, device, target_mode, recurse))
        ret = -1;

    return ret;
}

int pmgr_adt_power_enable(const char *path)
{
    printf("POWER ENABLE!!!!");
    mdelay(10000);
    int ret = pmgr_adt_devices_set_mode(path, PMGR_PS_ACTIVE, true);
    return ret;
}

int pmgr_adt_power_disable(const char *path)
{
    return pmgr_adt_devices_set_mode(path, PMGR_PS_PWRGATE, false);
}

int pmgr_adt_power_enable_index(const char *path, u32 index)
{
    int ret = pmgr_adt_device_set_mode(path, index, PMGR_PS_ACTIVE, true);
    return ret;
}

int pmgr_adt_power_disable_index(const char *path, u32 index)
{
    return pmgr_adt_device_set_mode(path, index, PMGR_PS_PWRGATE, false);
}

static int pmgr_reset_device(int die, const struct pmgr_device *dev)
{
    if (die < 0 || die > 16) {
        printf("pmgr: invalid die id %d for device %s\n", die, dev->name);
        return -1;
    }

    uintptr_t addr = pmgr_device_get_addr(die, dev);

    u32 reg = read32(addr);
    if (FIELD_GET(PMGR_PS_ACTUAL, reg) != PMGR_PS_ACTIVE) {
        printf("pmgr: will not reset disabled device %d.%s\n", die, dev->name);
        return -1;
    }

    printf("pmgr: resetting device %d.%s\n", die, dev->name);

    set32(addr, PMGR_DEV_DISABLE);
    set32(addr, PMGR_RESET);
    udelay(10);
    clear32(addr, PMGR_RESET);
    clear32(addr, PMGR_DEV_DISABLE);

    return 0;
}

int pmgr_adt_reset(const char *path)
{
    const u32 *devices;
    u32 n_devices;
    int ret = 0;

    if (pmgr_adt_find_devices(path, &devices, &n_devices) < 0)
        return -1;

    for (u32 i = 0; i < n_devices; ++i) {
        const struct pmgr_device *device;
        u16 id = FIELD_GET(PMGR_DEVICE_ID, devices[i]);
        u8 die = FIELD_GET(PMGR_DIE_ID, devices[i]);

        if (pmgr_find_device(id, &device)) {
            ret = -1;
            continue;
        }

        if (pmgr_reset_device(die, device))
            ret = -1;
    }

    return ret;
}

int pmgr_reset(int die, const char *name)
{
    const struct pmgr_device *dev = NULL;

    for (unsigned int i = 0; i < pmgr_devices_len; ++i) {
        if (strncmp(pmgr_devices[i].name, name, 0x10) == 0) {
            dev = &pmgr_devices[i];
            break;
        }
    }

    if (!dev)
        return -1;

    return pmgr_reset_device(die, dev);
}

int pmgr_init(void)
{
    printf("pmgr: pmgr_init()\n");

    int node = adt_path_offset(adt, "/arm-io");
    if (node < 0) {
        printf("pmgr: Error getting /arm-io node\n");
        return -1;
    }
    if (ADT_GETPROP(adt, node, "die-count", &pmgr_dies) < 0)
        pmgr_dies = 1;

    pmgr_offset = adt_path_offset_trace(adt, "/arm-io/pmgr", pmgr_path);
    if (pmgr_offset < 0) {
        printf("pmgr: Error getting /arm-io/pmgr node\n");
        return -1;
    }

    printf("pmgr: node: %d, pmgr_dies: %d, pmgr_offset: %d\n.", node, pmgr_dies, pmgr_offset);

#if TARGET == T6041
    struct ps_regs ps_regs_array[22];
    pmgr_ps_regs = ps_regs_array;
    pmgr_ps_regs_len = sizeof(ps_regs_array);
    ps_regs_array[0].reg        = 0x00000000;
    ps_regs_array[0].offset     = 0x00000000;
    ps_regs_array[0].mask       = 0x001FFFCF;

    ps_regs_array[1].reg        = 0x00000000;
    ps_regs_array[1].offset     = 0x00000100;
    ps_regs_array[1].mask       = 0x55557FFF;

    ps_regs_array[2].reg        = 0x00000000;
    ps_regs_array[2].offset     = 0x00000200;
    ps_regs_array[2].mask       = 0x55555555;

    ps_regs_array[3].reg        = 0x00000000;
    ps_regs_array[3].offset     = 0x00000300;
    ps_regs_array[3].mask       = 0x55555555;

    ps_regs_array[4].reg        = 0x00000000;
    ps_regs_array[4].offset     = 0x00000400;
    ps_regs_array[4].mask       = 0xFFFFFFFD;

    ps_regs_array[5].reg        = 0x00000000;
    ps_regs_array[5].offset     = 0x00000500;
    ps_regs_array[5].mask       = 0x07F81783;

    ps_regs_array[6].reg        = 0x00000000;
    ps_regs_array[6].offset     = 0x00000600;
    ps_regs_array[6].mask       = 0x00004080;

    ps_regs_array[7].reg        = 0x00000001;
    ps_regs_array[7].offset     = 0x00000200;
    ps_regs_array[7].mask       = 0xFFFDF800;

    ps_regs_array[8].reg        = 0x00000001;
    ps_regs_array[8].offset     = 0x00000100;
    ps_regs_array[8].mask       = 0x00000F57;

    ps_regs_array[9].reg        = 0x00000001;
    ps_regs_array[9].offset     = 0x00002000;
    ps_regs_array[9].mask       = 0x00000000;

    ps_regs_array[10].reg       = 0x00000001;
    ps_regs_array[10].offset    = 0x00004000;
    ps_regs_array[10].mask      = 0x00000000;

    ps_regs_array[11].reg       = 0x00000001;
    ps_regs_array[11].offset    = 0x00008000;
    ps_regs_array[11].mask      = 0x00000000;

    ps_regs_array[12].reg       = 0x00000002;
    ps_regs_array[12].offset    = 0x00000100;
    ps_regs_array[12].mask      = 0xAAAAAABF;

    ps_regs_array[13].reg       = 0x00000002;
    ps_regs_array[13].offset    = 0x00000200;
    ps_regs_array[13].mask      = 0xFFFFFFFF;

    ps_regs_array[14].reg       = 0x00000002;
    ps_regs_array[14].offset    = 0x00000300;
    ps_regs_array[14].mask      = 0x555557FF;

    ps_regs_array[15].reg       = 0x00000002;
    ps_regs_array[15].offset    = 0x00000400;
    ps_regs_array[15].mask      = 0xE0015555;

    ps_regs_array[16].reg       = 0x00000002;
    ps_regs_array[16].offset    = 0x00000500;
    ps_regs_array[16].mask      = 0x01B5559F;

    ps_regs_array[17].reg       = 0x00000002;
    ps_regs_array[17].offset    = 0x00000C00;
    ps_regs_array[17].mask      = 0x00000001;

    ps_regs_array[18].reg       = 0x00000002;
    ps_regs_array[18].offset    = 0x00004000;
    ps_regs_array[18].mask      = 0x000007C2;

    ps_regs_array[19].reg       = 0x00000002;
    ps_regs_array[19].offset    = 0x00008000;
    ps_regs_array[19].mask      = 0x0000001F;

    ps_regs_array[20].reg       = 0x00000036;
    ps_regs_array[20].offset    = 0x00000000;
    ps_regs_array[20].mask      = 0x00000001;

    ps_regs_array[21].reg       = 0x00000036;
    ps_regs_array[21].offset    = 0x00000100;
    ps_regs_array[21].mask      = 0x00000005;
#else
    pmgr_ps_regs = adt_getprop(adt, pmgr_offset, "ps-regs", &pmgr_ps_regs_len);
    if (pmgr_ps_regs == NULL || pmgr_ps_regs_len == 0) {
        printf("pmgr: Error getting /arm-io/pmgr ps-regs\n.");
        return -1;
    }
#endif

    pmgr_devices = adt_getprop(adt, pmgr_offset, "devices", &pmgr_devices_len);
    if (pmgr_devices == NULL || pmgr_devices_len == 0) {
        printf("pmgr: Error getting /arm-io/pmgr devices.\n");
        return -1;
    }

    pmgr_devices_len /= sizeof(*pmgr_devices);
    pmgr_initialized = 1;

    printf("pmgr: Cleaning up device states...\n");

    // detect whether u8 or u16 PMGR IDs are used by comparing the IDs of the
    // first 2 devices
    if (pmgr_devices_len >= 2)
        pmgr_u8id = pmgr_devices[0].id1 != pmgr_devices[1].id1;

    for (u8 die = 0; die < pmgr_dies; ++die) {
        for (size_t i = 0; i < pmgr_devices_len; ++i) {
            const struct pmgr_device *device = &pmgr_devices[i];

            if ((device->flags & PMGR_FLAG_VIRTUAL))
                continue;

            uintptr_t addr = pmgr_device_get_addr(die, device);
            if (!addr)
                continue;

            u32 reg = read32(addr);

            if (reg & PMGR_AUTO_ENABLE || FIELD_GET(PMGR_PS_TARGET, reg) == PMGR_PS_ACTIVE) {
                for (int j = 0; j < 2; j++) {
                    u16 parent[2];
                    pmgr_adt_get_parents(device, parent);
                    if (parent[j]) {
                        const struct pmgr_device *pdevice;
                        if (pmgr_find_device(parent[j], &pdevice)) {
                            printf("pmgr: Failed to find parent #%d for %s\n", parent[j],
                                   device->name);
                            continue;
                        }

                        if ((pdevice->flags & PMGR_FLAG_VIRTUAL))
                            continue;

                        addr = pmgr_device_get_addr(die, pdevice);
                        if (!addr)
                            continue;

                        reg = read32(addr);

                        if (!(reg & PMGR_AUTO_ENABLE) &&
                            FIELD_GET(PMGR_PS_TARGET, reg) != PMGR_PS_ACTIVE) {
                            printf("pmgr: Enabling %d.%s, parent of active device %s\n", die,
                                   pdevice->name, device->name);
                            pmgr_set_mode(addr, PMGR_PS_ACTIVE);
                        }
                    }
                }
            }
        }
    }

    printf("pmgr: initialized, %d devices on %u dies found.\n", pmgr_devices_len, pmgr_dies);

    return 0;
}

u32 pmgr_get_feature(const char *name)
{
    u32 val = 0;

    int node = adt_path_offset(adt, "/arm-io/pmgr");
    if (node < 0)
        return 0;

    if (ADT_GETPROP(adt, node, name, &val) < 0)
        return 0;

    return val;
}
