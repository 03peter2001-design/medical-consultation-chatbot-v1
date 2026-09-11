using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using ZXing;

if (args.Length != 1 || !File.Exists(args[0]))
{
    Console.Error.WriteLine("Usage: QrDecode <png-path>");
    return 2;
}

using var bitmap = new Bitmap(args[0]);
var rectangle = new Rectangle(0, 0, bitmap.Width, bitmap.Height);
var bitmapData = bitmap.LockBits(rectangle, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
byte[] pixels;
try
{
    pixels = new byte[Math.Abs(bitmapData.Stride) * bitmapData.Height];
    Marshal.Copy(bitmapData.Scan0, pixels, 0, pixels.Length);
}
finally
{
    bitmap.UnlockBits(bitmapData);
}

var luminance = new RGBLuminanceSource(
    pixels,
    bitmap.Width,
    bitmap.Height,
    RGBLuminanceSource.BitmapFormat.BGRA32);
var reader = new BarcodeReaderGeneric
{
    AutoRotate = true,
    Options = { TryHarder = true }
};
var result = reader.Decode(luminance);
if (result is null)
{
    Console.Error.WriteLine("QR decode returned no result.");
    return 1;
}

Console.WriteLine(result.Text);
return 0;
