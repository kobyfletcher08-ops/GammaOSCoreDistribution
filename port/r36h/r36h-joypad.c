// SPDX-License-Identifier: GPL-2.0-only
// RK3326 R36H GPIO buttons and four axes through the board's analog multiplexer.
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/iio/consumer.h>
#include <linux/input.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/property.h>

struct r36h_button {
    struct gpio_desc *gpio;
    unsigned int code;
};
struct r36h_pad {
    struct input_dev *input;
    struct iio_channel *adc;
    struct gpio_desc *mux_a, *mux_b, *mux_en;
    struct r36h_button *buttons;
    unsigned int count;
    bool invert_x, invert_y;
};

static void r36h_poll(struct input_dev *input)
{
    struct r36h_pad *pad = input_get_drvdata(input);
    static const unsigned int axes[] = { ABS_X, ABS_Y, ABS_RX, ABS_RY };
    unsigned int i;
    int value;

    for (i = 0; i < pad->count; i++) {
        value = gpiod_get_value_cansleep(pad->buttons[i].gpio);
        if (value >= 0)
            input_report_key(input, pad->buttons[i].code, value);
    }
    for (i = 0; i < ARRAY_SIZE(axes); i++) {
        /* Board reference uses physical selector levels, independent of
         * consumer GPIO active-low polarity. The enable pin is active low. */
        gpiod_set_raw_value_cansleep(pad->mux_a, i & 1);
        gpiod_set_raw_value_cansleep(pad->mux_b, (i >> 1) & 1);
        usleep_range(100, 200);
        if (iio_read_channel_raw(pad->adc, &value) < 0)
            continue;
        value = clamp(value, 0, 1023);
        if ((i == 0 && pad->invert_x) || (i == 1 && pad->invert_y))
            value = 1023 - value;
        input_report_abs(input, axes[i], value);
    }
    input_sync(input);
}

static void r36h_mux_disable(void *data)
{
    struct r36h_pad *pad = data;
    gpiod_set_raw_value_cansleep(pad->mux_en, 1);
}

static int r36h_probe(struct platform_device *pdev)
{
    struct device *dev = &pdev->dev;
    struct r36h_pad *pad;
    struct fwnode_handle *child;
    unsigned int count, i = 0;
    int ret;

    pad = devm_kzalloc(dev, sizeof(*pad), GFP_KERNEL);
    if (!pad)
        return -ENOMEM;
    pad->input = devm_input_allocate_device(dev);
    if (!pad->input)
        return -ENOMEM;
    pad->adc = devm_iio_channel_get(dev, "amux_adc");
    if (IS_ERR(pad->adc))
        return PTR_ERR(pad->adc);
    pad->mux_a = devm_gpiod_get(dev, "amux-a", GPIOD_OUT_LOW);
    if (IS_ERR(pad->mux_a))
        return PTR_ERR(pad->mux_a);
    pad->mux_b = devm_gpiod_get(dev, "amux-b", GPIOD_OUT_LOW);
    if (IS_ERR(pad->mux_b))
        return PTR_ERR(pad->mux_b);
    pad->mux_en = devm_gpiod_get(dev, "amux-en", GPIOD_OUT_LOW);
    if (IS_ERR(pad->mux_en))
        return PTR_ERR(pad->mux_en);
    ret = devm_add_action_or_reset(dev, r36h_mux_disable, pad);
    if (ret)
        return ret;
    count = device_get_child_node_count(dev);
    if (!count || count > 64)
        return -EINVAL;
    pad->buttons = devm_kcalloc(dev, count, sizeof(*pad->buttons), GFP_KERNEL);
    if (!pad->buttons)
        return -ENOMEM;
    device_for_each_child_node(dev, child) {
        u32 code;
        ret = fwnode_property_read_u32(child, "linux,code", &code);
        if (ret || code > KEY_MAX) {
            fwnode_handle_put(child);
            return -EINVAL;
        }
        pad->buttons[i].gpio = devm_fwnode_gpiod_get_index(dev, child, NULL, 0,
                                                        GPIOD_IN, "r36h-button");
        if (IS_ERR(pad->buttons[i].gpio)) {
            ret = PTR_ERR(pad->buttons[i].gpio);
            fwnode_handle_put(child);
            return ret;
        }
        pad->buttons[i].code = code;
        input_set_capability(pad->input, EV_KEY, code);
        i++;
    }
    pad->count = i;
    pad->invert_x = device_property_read_bool(dev, "invert-absx");
    pad->invert_y = device_property_read_bool(dev, "invert-absy");
    input_set_abs_params(pad->input, ABS_X, 0, 1023, 8, 32);
    input_set_abs_params(pad->input, ABS_Y, 0, 1023, 8, 32);
    input_set_abs_params(pad->input, ABS_RX, 0, 1023, 8, 32);
    input_set_abs_params(pad->input, ABS_RY, 0, 1023, 8, 32);
    pad->input->name = "R36H Gamepad";
    pad->input->phys = "r36h/input0";
    pad->input->id.bustype = BUS_HOST;
    pad->input->id.vendor = 0x1209;
    pad->input->id.product = 0x3636;
    pad->input->id.version = 1;
    input_set_drvdata(pad->input, pad);
    ret = input_setup_polling(pad->input, r36h_poll);
    if (ret)
        return ret;
    input_set_poll_interval(pad->input, 10);
    input_set_min_poll_interval(pad->input, 5);
    input_set_max_poll_interval(pad->input, 50);
    gpiod_set_raw_value_cansleep(pad->mux_en, 0);
    return input_register_device(pad->input);
}

static const struct of_device_id r36h_of_match[] = {
    { .compatible = "gammaos,r36h-joypad" },
    { }
};
MODULE_DEVICE_TABLE(of, r36h_of_match);
static struct platform_driver r36h_driver = {
    .probe = r36h_probe,
    .driver = { .name = "r36h-joypad", .of_match_table = r36h_of_match },
};
module_platform_driver(r36h_driver);
MODULE_DESCRIPTION("R36H GPIO and ADC-multiplexer gamepad");
MODULE_LICENSE("GPL");
