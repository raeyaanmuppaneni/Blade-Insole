/*
 * TI FDC2214 register map and the settings this board needs.
 * Values cross-checked against the TI datasheet (SNOSCZ5) register section.
 */
#ifndef FDC2214_H
#define FDC2214_H

#include <stdint.h>

#define FDC_ADDR_L          0x2A    /* ADDR pin tied low  */
#define FDC_ADDR_H          0x2B    /* ADDR pin tied high */

#define FDC_REG_DATA_MSB(ch)        (0x00 + 2 * (ch))   /* [15:12] error flags, [11:0] data[27:16] */
#define FDC_REG_DATA_LSB(ch)        (0x01 + 2 * (ch))   /* data[15:0] */
#define FDC_REG_RCOUNT(ch)          (0x08 + (ch))
#define FDC_REG_OFFSET(ch)          (0x0C + (ch))
#define FDC_REG_SETTLECOUNT(ch)     (0x10 + (ch))
#define FDC_REG_CLOCK_DIVIDERS(ch)  (0x14 + (ch))
#define FDC_REG_STATUS              0x18
#define FDC_REG_ERROR_CONFIG        0x19
#define FDC_REG_CONFIG              0x1A
#define FDC_REG_MUX_CONFIG          0x1B
#define FDC_REG_RESET_DEV           0x1C
#define FDC_REG_DRIVE_CURRENT(ch)   (0x1E + (ch))
#define FDC_REG_MANUFACTURER_ID     0x7E
#define FDC_REG_DEVICE_ID           0x7F

#define FDC_MANUFACTURER_TI         0x5449
#define FDC_DEVICE_ID_2214          0x3055

#define FDC_DATA_MASK               0x0FFFu   /* data bits inside the MSB register */
#define FDC_ERR_MASK                0xF000u   /* under/over-range, watchdog, amplitude */

/*
 * CONFIG (0x1A), bit by bit:
 *   [13] SLEEP_MODE_EN     1 = asleep while we configure it
 *   [12] reserved, must be 1
 *   [11] SENSOR_ACTIVATE_SEL 0 = full-current start-up (our LC tanks are high-Q)
 *   [10] reserved, must be 1
 *   [9]  REF_CLK_SRC       1 = use the CLKIN pin, i.e. the MCU's clock on PA8
 *   [7]  INTB_DIS          1 = no interrupt pin; we poll
 *   [5:0] reserved, must be 000001
 */
#define FDC_CONFIG_SLEEP    0x3681u
#define FDC_CONFIG_RUN      0x1681u

/*
 * MUX_CONFIG (0x1B):
 *   [15] AUTOSCAN_EN  1 = cycle through channels by itself
 *   [14:13] RR_SEQUENCE 10 = channels 0,1,2,3
 *   [12:3] reserved, must be 00 0100 0001
 *   [2:0] DEGLITCH    101 = 10 MHz filter (our tanks resonate near 6.5 MHz)
 */
#define FDC_MUX_CONFIG_4CH  0xC20Du

/*
 * CLOCK_DIVIDERS (0x14+ch):
 *   [13:12] FIN_SEL      10 = divide-by-2 input path, valid to 10 MHz
 *   [9:0]   FREF_DIVIDER 1  = use CLKIN as-is
 * With divide-by-2, frequency = 2 * f_ref * data / 2^28.
 */
#define FDC_CLOCK_DIVIDERS  0x2001u
#define FDC_FIN_SEL         2u

/* Drive current per channel, bits [15:11]. 0x1F is maximum; the LC tanks need
 * enough current to sustain oscillation. Tune after seeing real amplitudes. */
#define FDC_DRIVE_CURRENT   0xF800u

#define FDC_CHANNELS        4
#define FDC_CHIPS           2

/* Timing targets; converted to register counts using the actual reference clock.
 * Count = time * f_ref / 16, for both the settle and conversion intervals. */
#define FDC_SETTLE_US       50u
#define FDC_CONVERT_US      1500u

#endif /* FDC2214_H */
