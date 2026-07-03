/* SPDX-License-Identifier: MIT */

#include "usb.h"
#include "adt.h"
#include "dart.h"
#include "i2c.h"
#include "iodev.h"
#include "malloc.h"
#include "pmgr.h"
#include "spmi.h"
#include "string.h"
#include "tps6598x.h"
#include "types.h"
#include "usb_dwc3.h"
#include "usb_dwc3_regs.h"
#include "utils.h"
#include "vsprintf.h"

struct usb_drd_regs {
    uintptr_t drd_regs;
    uintptr_t drd_regs_unk3;
    uintptr_t atc;
};

#if USB_IODEV_COUNT > 100
#error "USB_IODEV_COUNT is limited to 100 to prevent overflow in ADT path names"
#endif

#ifdef USE_DEBUG_USB
#define FIRST_USB_IODEV 1
#else
#define FIRST_USB_IODEV 0
#endif

// length of the format string is is used as buffer size
// limits the USB instance numbers to reasonable 2 digits
#define FMT_DART_PATH        "/arm-io/dart-usb%u"
#define FMT_DART_MAPPER_PATH "/arm-io/dart-usb%u/mapper-usb%u"
#define FMT_ATC_PATH         "/arm-io/atc-phy%u"
#define FMT_DRD_PATH         "/arm-io/usb-drd%u"
// HPM_PATH string is at most
// "/arm-io/i2cX" (12) + "/" + hpmBusManagerX (14) + "/" + "hpmX" (4) + '\0'
#define MAX_HPM_PATH_LEN 40

static tps6598x_irq_state_t tps6598x_irq_state[USB_IODEV_COUNT];
static bool usb_is_initialized = false;

#define PIPEHANDLER_MUX_CTRL             0x0c
#define PIPEHANDLER_MUX_CTRL_USB3        0x08
#define PIPEHANDLER_MUX_CTRL_USB4_TUNNEL 0x11
#define PIPEHANDLER_MUX_CTRL_DUMMY       0x22

#define PIPEHANDLER_LOCK_REQ 0x10
#define PIPEHANDLER_LOCK_ACK 0x14
#define PIPEHANDLER_LOCK_EN  BIT(0)

#define PIPEHANDLER_AON_GEN                     0x1C
#define PIPEHANDLER_AON_GEN_DWC3_FORCE_CLAMP_EN BIT(4)
#define PIPEHANDLER_AON_GEN_DWC3_RESET_N        BIT(0)

#define PIPEHANDLER_NONSELECTED_OVERRIDE 0x20
#define PIPEHANDLER_NATIVE_RESET         BIT(12)
#define PIPEHANDLER_DUMMY_PHY_EN         BIT(15)
#define PIPEHANDLER_NATIVE_POWER_DOWN    GENMASK(3, 0)

static dart_dev_t *usb_dart_init(u32 idx)
{
    int mapper_offset;
    char path[sizeof(FMT_DART_MAPPER_PATH)];

    snprintf(path, sizeof(path), FMT_DART_MAPPER_PATH, idx, idx);
    mapper_offset = adt_path_offset(adt, path);
    if (mapper_offset < 0) {
        // Device not present
        return NULL;
    }

    u32 dart_idx;
    if (ADT_GETPROP(adt, mapper_offset, "reg", &dart_idx) < 0) {
        printf("usb: Error getting DART %s device index/\n", path);
        return NULL;
    }

    snprintf(path, sizeof(path), FMT_DART_PATH, idx);
    return dart_init_adt(path, 1, dart_idx, false);
}

static int usb_drd_get_regs(u32 idx, struct usb_drd_regs *regs)
{
    int adt_drd_path[8];
    int adt_drd_offset;
    int adt_phy_path[8];
    int adt_phy_offset;
    char phy_path[sizeof(FMT_ATC_PATH)];
    char drd_path[sizeof(FMT_DRD_PATH)];

    snprintf(drd_path, sizeof(drd_path), FMT_DRD_PATH, idx);
    adt_drd_offset = adt_path_offset_trace(adt, drd_path, adt_drd_path);
    if (adt_drd_offset < 0) {
        // Nonexistent device
        return -1;
    }

    snprintf(phy_path, sizeof(phy_path), FMT_ATC_PATH, idx);
    adt_phy_offset = adt_path_offset_trace(adt, phy_path, adt_phy_path);
    if (adt_phy_offset < 0) {
        printf("usb: Error getting phy node %s\n", phy_path);
        return -1;
    }

    if (adt_get_reg(adt, adt_phy_path, "reg", 0, &regs->atc, NULL) < 0) {
        printf("usb: Error getting reg with index 0 for %s.\n", phy_path);
        return -1;
    }
    if (adt_get_reg(adt, adt_drd_path, "reg", 0, &regs->drd_regs, NULL) < 0) {
        printf("usb: Error getting reg with index 0 for %s.\n", drd_path);
        return -1;
    }
    if (adt_get_reg(adt, adt_drd_path, "reg", 3, &regs->drd_regs_unk3, NULL) < 0) {
        printf("usb: Error getting reg with index 3 for %s.\n", drd_path);
        return -1;
    }

    return 0;
}

/* USB2 PHY registers (bring-up naming borrowed from Linux atc.c) */
#define USB2PHY_USBCTL           0x00
#define USB2PHY_USBCTL_RUN       BIT(1)
#define USB2PHY_USBCTL_ISOLATION BIT(2)

#define USB2PHY_CTL             0x04
#define USB2PHY_CTL_RESET       BIT(0)
#define USB2PHY_CTL_PORT_RESET  BIT(1)
#define USB2PHY_CTL_APB_RESET_N BIT(2)
#define USB2PHY_CTL_SIDDQ       BIT(3)

#define USB2PHY_SIG             0x08
#define USB2PHY_SIG_VBUS_FORCES 0xf /* VBUSDET/VBUSVLDEXT force val+en */
#define USB2PHY_SIG_HOST        (7 << 12)

#define USB2PHY_MISCTUNE                 0x1c
#define USB2PHY_MISCTUNE_APBCLK_GATE_OFF BIT(29)
#define USB2PHY_MISCTUNE_REFCLK_GATE_OFF BIT(30)

/*
 * T6041 bring-up hack: reconfigure a port's USB2 PHY from the device mode
 * usb_phy_bringup() leaves behind to HOST mode, so a plain dwc3 host stack
 * ("snps,dwc3" + dr_mode="host", no ATC-PHY/PD driver) works in Linux.
 *
 * Mirrors Linux atc.c: atcphy_dwc3_reset_assert -> atcphy_usb2_power_off ->
 * set USB2PHY_SIG_HOST while the PHY is off (dwc3-apple.c: the mode "must be
 * configured while it is still powered off") -> atcphy_usb2_power_on ->
 * atcphy_dwc3_reset_deassert.
 */
int usb_phy_bringup_host(u32 idx)
{
    if (idx >= USB_IODEV_COUNT)
        return -1;

    struct usb_drd_regs r;
    if (usb_drd_get_regs(idx, &r) < 0)
        return -1;

    /* dwc3 reset assert */
    clear32(r.drd_regs_unk3 + PIPEHANDLER_AON_GEN, PIPEHANDLER_AON_GEN_DWC3_RESET_N);
    set32(r.drd_regs_unk3 + PIPEHANDLER_AON_GEN, PIPEHANDLER_AON_GEN_DWC3_FORCE_CLAMP_EN);

    /* usb2 phy power off */
    write32(r.atc + USB2PHY_USBCTL, USB2PHY_USBCTL_ISOLATION);
    udelay(10);
    set32(r.atc + USB2PHY_CTL, USB2PHY_CTL_SIDDQ);
    udelay(10);
    set32(r.atc + USB2PHY_CTL, USB2PHY_CTL_PORT_RESET);
    udelay(10);
    set32(r.atc + USB2PHY_CTL, USB2PHY_CTL_RESET);
    udelay(10);
    clear32(r.atc + USB2PHY_CTL, USB2PHY_CTL_APB_RESET_N);
    udelay(10);
    set32(r.atc + USB2PHY_MISCTUNE, USB2PHY_MISCTUNE_APBCLK_GATE_OFF);
    set32(r.atc + USB2PHY_MISCTUNE, USB2PHY_MISCTUNE_REFCLK_GATE_OFF);

    /* host mode, while the PHY is off */
    set32(r.atc + USB2PHY_SIG, USB2PHY_SIG_HOST);

    /* usb2 phy power on */
    set32(r.atc + USB2PHY_SIG, USB2PHY_SIG_VBUS_FORCES);
    udelay(10);
    clear32(r.atc + USB2PHY_CTL, USB2PHY_CTL_SIDDQ);
    udelay(10);
    clear32(r.atc + USB2PHY_CTL, USB2PHY_CTL_RESET);
    udelay(10);
    clear32(r.atc + USB2PHY_CTL, USB2PHY_CTL_PORT_RESET);
    udelay(10);
    set32(r.atc + USB2PHY_CTL, USB2PHY_CTL_APB_RESET_N);
    udelay(10);
    clear32(r.atc + USB2PHY_MISCTUNE, USB2PHY_MISCTUNE_APBCLK_GATE_OFF);
    clear32(r.atc + USB2PHY_MISCTUNE, USB2PHY_MISCTUNE_REFCLK_GATE_OFF);
    write32(r.atc + USB2PHY_USBCTL, USB2PHY_USBCTL_RUN);

    /* keep the dummy USB3 pipe mux + override usb_phy_bringup() set up */
    write32(r.drd_regs_unk3 + PIPEHANDLER_MUX_CTRL, PIPEHANDLER_MUX_CTRL_DUMMY);
    write32(r.drd_regs_unk3 + PIPEHANDLER_NONSELECTED_OVERRIDE, 0x9332);

    /* dwc3 reset deassert */
    clear32(r.drd_regs_unk3 + PIPEHANDLER_AON_GEN, PIPEHANDLER_AON_GEN_DWC3_FORCE_CLAMP_EN);
    set32(r.drd_regs_unk3 + PIPEHANDLER_AON_GEN, PIPEHANDLER_AON_GEN_DWC3_RESET_N);

    printf("usb: port %d USB2 PHY switched to host mode\n", idx);
    return 0;
}

int usb_phy_bringup(u32 idx)
{
    char path[24];

    if (idx >= USB_IODEV_COUNT)
        return -1;

    struct usb_drd_regs usb_regs;
    if (usb_drd_get_regs(idx, &usb_regs) < 0)
        return -1;

    snprintf(path, sizeof(path), FMT_ATC_PATH, idx);
    if (pmgr_adt_power_enable(path) < 0)
        return -1;

    snprintf(path, sizeof(path), FMT_DART_PATH, idx);
    if (pmgr_adt_power_enable(path) < 0)
        return -1;

    snprintf(path, sizeof(path), FMT_DRD_PATH, idx);
    if (pmgr_adt_power_enable(path) < 0)
        return -1;

    write32(usb_regs.atc + 0x08, 0x01c1000f);
    write32(usb_regs.atc + 0x04, 0x00000003);
    write32(usb_regs.atc + 0x04, 0x00000000);
    write32(usb_regs.atc + 0x1c, 0x008c0813);
    write32(usb_regs.atc + 0x00, 0x00000002);

    write32(usb_regs.drd_regs_unk3 + PIPEHANDLER_MUX_CTRL, PIPEHANDLER_MUX_CTRL_DUMMY);
    write32(usb_regs.drd_regs_unk3 + PIPEHANDLER_AON_GEN, PIPEHANDLER_AON_GEN_DWC3_RESET_N);
    write32(usb_regs.drd_regs_unk3 + PIPEHANDLER_NONSELECTED_OVERRIDE, 0x9332);

    return 0;
}

dwc3_dev_t *usb_iodev_bringup(u32 idx)
{
    dart_dev_t *usb_dart = usb_dart_init(idx);
    if (!usb_dart)
        return NULL;

    struct usb_drd_regs usb_reg;
    if (usb_drd_get_regs(idx, &usb_reg) < 0)
        return NULL;

    return usb_dwc3_init(usb_reg.drd_regs, usb_dart);
}

#define USB_IODEV_WRAPPER(name, pipe)                                                              \
    static ssize_t usb_##name##_can_read(void *dev)                                                \
    {                                                                                              \
        return usb_dwc3_can_read(dev, pipe);                                                       \
    }                                                                                              \
                                                                                                   \
    static bool usb_##name##_can_write(void *dev)                                                  \
    {                                                                                              \
        return usb_dwc3_can_write(dev, pipe);                                                      \
    }                                                                                              \
                                                                                                   \
    static ssize_t usb_##name##_read(void *dev, void *buf, size_t count)                           \
    {                                                                                              \
        return usb_dwc3_read(dev, pipe, buf, count);                                               \
    }                                                                                              \
                                                                                                   \
    static ssize_t usb_##name##_write(void *dev, const void *buf, size_t count)                    \
    {                                                                                              \
        return usb_dwc3_write(dev, pipe, buf, count);                                              \
    }                                                                                              \
                                                                                                   \
    static ssize_t usb_##name##_queue(void *dev, const void *buf, size_t count)                    \
    {                                                                                              \
        return usb_dwc3_queue(dev, pipe, buf, count);                                              \
    }                                                                                              \
                                                                                                   \
    static void usb_##name##_handle_events(void *dev)                                              \
    {                                                                                              \
        usb_dwc3_handle_events(dev);                                                               \
    }                                                                                              \
                                                                                                   \
    static void usb_##name##_flush(void *dev)                                                      \
    {                                                                                              \
        usb_dwc3_flush(dev, pipe);                                                                 \
    }

USB_IODEV_WRAPPER(0, CDC_ACM_PIPE_0)
USB_IODEV_WRAPPER(1, CDC_ACM_PIPE_1)

static struct iodev_ops iodev_usb_ops = {
    .can_read = usb_0_can_read,
    .can_write = usb_0_can_write,
    .read = usb_0_read,
    .write = usb_0_write,
    .queue = usb_0_queue,
    .flush = usb_0_flush,
    .handle_events = usb_0_handle_events,
};

static struct iodev_ops iodev_usb_sec_ops = {
    .can_read = usb_1_can_read,
    .can_write = usb_1_can_write,
    .read = usb_1_read,
    .write = usb_1_write,
    .queue = usb_1_queue,
    .flush = usb_1_flush,
    .handle_events = usb_1_handle_events,
};

struct iodev iodev_usb_vuart = {
    .ops = &iodev_usb_sec_ops,
    .usage = 0,
    .lock = SPINLOCK_INIT,
};

static tps6598x_dev_t *hpm_init(i2c_dev_t *i2c, const char *hpm_path)
{
    tps6598x_dev_t *tps = tps6598x_init(hpm_path, i2c);
    if (!tps) {
        printf("usb: tps6598x_init failed for %s.\n", hpm_path);
        return NULL;
    }

    if (tps6598x_powerup(tps) < 0) {
        printf("usb: tps6598x_powerup failed for %s.\n", hpm_path);
        tps6598x_shutdown(tps);
        return NULL;
    }

    return tps;
}

void usb_spmi_init(void)
{
    /*
     * Power the ACE3s up to S0 so the ports can source VBUS / act as DFP
     * (needed for USB host mode in the booted OS). Works when running at
     * EL2 (bare m1n1); under the m1n1 HV the guest's SPMI commands get no
     * reply and this fails gracefully — the host m1n1 already did it.
     */
    usb_spmi_powerup_hpms();

    for (int idx = 0; idx < USB_IODEV_COUNT; ++idx)
        usb_phy_bringup(idx); /* Fails on missing devices, just continue */

    usb_is_initialized = true;
}

/*
 * ACE3 (usbc,sn201202x,spmi) access: the classic TPS6598x/CD321x I2C register
 * map ("logical registers") tunneled over SPMI. Transport per
 * https://asahilinux.org/docs/hw/peripherals/ace3/:
 * write 0x80|lreg to SPMI reg 0x00, poll bit7 clear, then the logical
 * register data window is SPMI regs 0x20.. (reads mirror it, writes commit).
 */
#define ACE3_REG_SEL  0x00
#define ACE3_SEL_BUSY 0x80
#define ACE3_REG_SIZE 0x1f
#define ACE3_REG_DATA 0x20

#define ACE3_LREG_CMD1        0x08
#define ACE3_LREG_DATA1       0x09
#define ACE3_LREG_POWER_STATE 0x20
#define ACE3_CMD_INVALID      0x444d4321 // "!CMD" as LE u32

static int ace3_select(spmi_dev_t *spmi, u8 slave, u8 lreg)
{
    /*
     * The selection MUST use the basic register write/read SPMI opcodes;
     * extended access to reg 0x00 is ACKed but treated as a "normal write"
     * that does not trigger the selection (hardware-verified: SEL_BUSY
     * never clears when written via SPMI_OPC_EXT_WRITE).
     *
     * The real completion signal is an interrupt through the SPMI
     * controller; all we can do is poll the busy bit, which is racy right
     * after issuing the command (the register still reads its pre-command
     * value until the hardware picks it up, and the final value is not
     * reliably the selected address either — hardware-verified both ways).
     * Wait for the hardware to assert busy first, then poll for it to
     * clear, accepting whatever value remains.
     */
    /*
     * The chip is deaf to its first transactions after a cold boot (it
     * silently swallows commands for a while, hardware-verified) — a
     * generous retry budget with real gaps between attempts is required
     * this early in boot.
     */
    u8 v;
    for (int attempt = 0; attempt < 10; attempt++) {
        if (attempt)
            udelay(10000);
        if (spmi_reg_write(spmi, slave, ACE3_REG_SEL, ACE3_SEL_BUSY | lreg) < 0)
            return -1;
        udelay(1000);
        for (int i = 0; i < 1000; i++) {
            if (spmi_reg_read(spmi, slave, ACE3_REG_SEL, &v) < 0)
                return -1;
            if (!(v & ACE3_SEL_BUSY))
                break;
            udelay(100);
        }
        if (v & ACE3_SEL_BUSY)
            continue;
        /* a successful selection latches the (non-zero) size into 0x1f */
        if (spmi_reg_read(spmi, slave, ACE3_REG_SIZE, &v) < 0)
            return -1;
        if (v)
            return 0;
    }
    return -1;
}

static int ace3_lread(spmi_dev_t *spmi, u8 slave, u8 lreg, u8 *bfr, size_t len)
{
    if (ace3_select(spmi, slave, lreg) < 0)
        return -1;
    return spmi_ext_read(spmi, slave, ACE3_REG_DATA, bfr, len);
}

static int ace3_lwrite(spmi_dev_t *spmi, u8 slave, u8 lreg, const u8 *bfr, size_t len)
{
    if (ace3_select(spmi, slave, lreg) < 0)
        return -1;
    return spmi_ext_write(spmi, slave, ACE3_REG_DATA, bfr, len);
}

static int ace3_command(spmi_dev_t *spmi, u8 slave, const char *cmd, const u8 *data, size_t len)
{
    u32 status;

    if (len && ace3_lwrite(spmi, slave, ACE3_LREG_DATA1, data, len) < 0)
        return -1;
    if (ace3_lwrite(spmi, slave, ACE3_LREG_CMD1, (const u8 *)cmd, 4) < 0)
        return -1;
    for (int i = 0; i < 200; i++) {
        if (ace3_lread(spmi, slave, ACE3_LREG_CMD1, (u8 *)&status, 4) < 0)
            return -1;
        if (status == ACE3_CMD_INVALID)
            return -1;
        if (status == 0)
            return 0;
        udelay(500);
    }
    return -1;
}

/*
 * Put the ACE3 USB-PD controllers of the user-facing USB-C ports (except
 * port 0) into system power state S0 via the "SSPS" command — the SPMI
 * equivalent of tps6598x_powerup(). iBoot leaves them in a low power state
 * (POWER_STATE=7, hardware-verified on T6041) where the port works as
 * sink/UFP only: it never sources VBUS or acts as DFP, so USB host mode
 * sees no device attach. Port 0 (rid 0) is skipped: it carries the m1n1
 * proxy/console under the HV, and device mode works fine in the low state.
 * Non-data ports (MagSafe, port-type != 2) are skipped too.
 */
void usb_spmi_powerup_hpms(void)
{
    char path[24];

    for (int bus = 0; bus < 8; bus++) {
        snprintf(path, sizeof(path), "/arm-io/nub-spmi-a%d", bus);
        int parent = adt_path_offset(adt, path);
        if (parent < 0)
            continue;

        spmi_dev_t *spmi = NULL;
        int node = parent;
        ADT_FOREACH_CHILD(adt, node)
        {
            if (!adt_is_compatible(adt, node, "usbc,sn201202x,spmi"))
                continue;

            u32 rid, port_type = 0, len = 0;
            if (ADT_GETPROP(adt, node, "rid", &rid) < 0 || rid == 0)
                continue;
            ADT_GETPROP(adt, node, "port-type", &port_type);
            if (port_type != 2)
                continue;
            const u32 *reg = adt_getprop(adt, node, "reg", &len);
            if (!reg || len < 4)
                continue;
            u8 slave = reg[0];

            if (!spmi) {
                spmi = spmi_init(path);
                if (!spmi) {
                    printf("usb: spmi_init failed for %s\n", path);
                    break;
                }
            }

            u8 pstate;
            if (ace3_lread(spmi, slave, ACE3_LREG_POWER_STATE, &pstate, 1) < 0) {
                printf("usb: hpm rid %d: POWER_STATE read failed\n", rid);
                continue;
            }
            if (pstate == 0)
                continue;

            const u8 s0 = 0;
            if (ace3_command(spmi, slave, "SSPS", &s0, 1) < 0) {
                printf("usb: hpm rid %d: SSPS failed\n", rid);
                continue;
            }
            printf("usb: hpm rid %d powered up (POWER_STATE %d -> S0)\n", rid, pstate);
        }

        if (spmi)
            spmi_shutdown(spmi);
    }
}

static int usb_init_i2c(const char *i2c_path)
{
    char hpm_path[MAX_HPM_PATH_LEN];

    int node = adt_path_offset(adt, i2c_path);
    if (node < 0)
        return 0;

    node = adt_first_child_offset(adt, node);
    if (node < 0)
        return 0;

    if (!adt_is_compatible(adt, node, "usbc,manager"))
        return 0;

    const char *hpm_mngr_name = adt_get_name(adt, node);
    if (!hpm_mngr_name || strnlen(hpm_mngr_name, 16) >= 16)
        return 0;

    i2c_dev_t *i2c = i2c_init(i2c_path);
    if (!i2c) {
        printf("usb: i2c init failed for %s\n", i2c_path);
        return -1;
    }

    ADT_FOREACH_CHILD(adt, node)
    {
        const char *name = adt_get_name(adt, node);
        if (!name || memcmp(name, "hpm", 3) || name[4] != '\0')
            continue; // unexpected hpm node name
        u32 idx = name[3] - '0';
        if (idx >= USB_IODEV_COUNT)
            continue; // unexpected hpm index

        snprintf(hpm_path, sizeof(hpm_path), "%s/%s/%s", i2c_path, hpm_mngr_name, name);

        tps6598x_dev_t *tps = hpm_init(i2c, hpm_path);
        if (!tps) {
            printf("usb: failed to init %s\n", name);
            continue;
        }

        if (tps6598x_disable_irqs(tps, &tps6598x_irq_state[idx]))
            printf("usb: unable to disable IRQ masks for %s\n", name);

        tps6598x_shutdown(tps);
    }

    i2c_shutdown(i2c);

    return 0;
}

void usb_init(void)
{
    if (usb_is_initialized)
        return;

    /*
     * M3/M4 models do not use i2c, but instead SPMI with a new controller.
     * We can get USB going for now by just bringing up the phys.
     */
    if (adt_path_offset(adt, "/arm-io/nub-spmi-a0/hpm0") > 0) {
        usb_spmi_init();
        return;
    }

    /*
     * A7-A11 uses a custom internal otg controller with the peripheral part
     * being dwc2.
     */
    if (adt_path_offset(adt, "/arm-io/otgphyctrl") > 0 &&
        adt_path_offset(adt, "/arm-io/usb-complex") > 0) {
        /* We do not support the custom controller and dwc2 (yet). */
        return;
    }

    if (adt_is_compatible(adt, 0, "J180dAP") && usb_init_i2c("/arm-io/i2c3") < 0)
        return;
    if (usb_init_i2c("/arm-io/i2c0") < 0)
        return;

    for (int idx = 0; idx < USB_IODEV_COUNT; ++idx)
        usb_phy_bringup(idx); /* Fails on missing devices, just continue */

    usb_is_initialized = true;
}

void usb_i2c_restore_irqs(const char *i2c_path, bool force)
{
    char hpm_path[MAX_HPM_PATH_LEN];

    int node = adt_path_offset(adt, i2c_path);
    if (node < 0)
        return;

    node = adt_first_child_offset(adt, node);
    if (node < 0)
        return;

    if (!adt_is_compatible(adt, node, "usbc,manager"))
        return;

    const char *hpm_mngr_name = adt_get_name(adt, node);
    if (!hpm_mngr_name || strnlen(hpm_mngr_name, 16) >= 16)
        return;

    i2c_dev_t *i2c = i2c_init(i2c_path);
    if (!i2c) {
        printf("usb: i2c init failed.\n");
        return;
    }

    ADT_FOREACH_CHILD(adt, node)
    {
        const char *name = adt_get_name(adt, node);
        if (!name || memcmp(name, "hpm", 3) || name[4] != '\0')
            continue; // unexpected hpm node name
        u32 idx = name[3] - '0';
        if (idx >= USB_IODEV_COUNT)
            continue; // unexpected hpm index

        if (iodev_get_usage(IODEV_USB0 + idx) && !force)
            continue;

        if (tps6598x_irq_state[idx].valid) {
            snprintf(hpm_path, sizeof(hpm_path), "%s/%s/%s", i2c_path, hpm_mngr_name, name);
            tps6598x_dev_t *tps = hpm_init(i2c, hpm_path);
            if (!tps)
                continue;

            if (tps6598x_restore_irqs(tps, &tps6598x_irq_state[idx]))
                printf("usb: unable to restore IRQ masks for %s\n", name);

            tps6598x_shutdown(tps);
        }
    }

    i2c_shutdown(i2c);
}

void usb_hpm_restore_irqs(bool force)
{
    /*
     * Do not try to restore irqs on M3/M4 which don't use i2c
     */
    if (adt_path_offset(adt, "/arm-io/nub-spmi-a0/hpm0") > 0)
        return;

    /*
     * Do not try to restore irqs on A7-A11 which don't use i2c
     */
    if (adt_path_offset(adt, "/arm-io/otgphyctrl") > 0 &&
        adt_path_offset(adt, "/arm-io/usb-complex") > 0)
        return;

    if (adt_is_compatible(adt, 0, "J180dAP"))
        usb_i2c_restore_irqs("/arm-io/i2c3", force);
    usb_i2c_restore_irqs("/arm-io/i2c0", force);
}

void usb_iodev_init(void)
{
    for (int i = FIRST_USB_IODEV; i < USB_IODEV_COUNT; i++) {
        dwc3_dev_t *opaque;
        struct iodev *usb_iodev;

        opaque = usb_iodev_bringup(i);
        if (!opaque)
            continue;

        usb_iodev = memalign(SPINLOCK_ALIGN, sizeof(*usb_iodev));
        if (!usb_iodev)
            continue;

        usb_iodev->ops = &iodev_usb_ops;
        usb_iodev->opaque = opaque;
        usb_iodev->usage = USAGE_CONSOLE | USAGE_UARTPROXY;
        spin_init(&usb_iodev->lock);

        iodev_register_device(IODEV_USB0 + i, usb_iodev);
        printf("USB%d: initialized at %p\n", i, opaque);
    }
}

void usb_iodev_shutdown(void)
{
    for (int i = FIRST_USB_IODEV; i < USB_IODEV_COUNT; i++) {
        struct iodev *usb_iodev = iodev_unregister_device(IODEV_USB0 + i);
        if (!usb_iodev)
            continue;

        printf("USB%d: shutdown\n", i);
        usb_dwc3_shutdown(usb_iodev->opaque);
        free(usb_iodev);
    }
}

void usb_iodev_vuart_setup(iodev_id_t iodev)
{
    if (iodev < IODEV_USB0 || iodev >= IODEV_USB0 + USB_IODEV_COUNT)
        return;

    iodev_usb_vuart.opaque = iodev_get_opaque(iodev);
}
