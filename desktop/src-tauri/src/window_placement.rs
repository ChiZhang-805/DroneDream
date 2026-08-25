use std::{mem::size_of, ptr::null_mut};

use tauri::{Runtime, WebviewWindow};
use windows_sys::Win32::{
    Foundation::{HWND, RECT},
    Graphics::Gdi::{GetMonitorInfoW, MonitorFromWindow, MONITORINFO, MONITOR_DEFAULTTONEAREST},
    UI::WindowsAndMessaging::{
        GetWindowRect, IsIconic, IsZoomed, SetWindowPos, SWP_NOACTIVATE, SWP_NOOWNERZORDER,
        SWP_NOZORDER,
    },
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct PixelRect {
    left: i32,
    top: i32,
    right: i32,
    bottom: i32,
}

impl PixelRect {
    fn width(self) -> Option<i32> {
        self.right.checked_sub(self.left).filter(|width| *width > 0)
    }

    fn height(self) -> Option<i32> {
        self.bottom
            .checked_sub(self.top)
            .filter(|height| *height > 0)
    }
}

impl From<RECT> for PixelRect {
    fn from(rect: RECT) -> Self {
        Self {
            left: rect.left,
            top: rect.top,
            right: rect.right,
            bottom: rect.bottom,
        }
    }
}

fn clamp_rect_to_work_area(window: PixelRect, work_area: PixelRect) -> Option<PixelRect> {
    let window_width = window.width()?;
    let window_height = window.height()?;
    let work_width = work_area.width()?;
    let work_height = work_area.height()?;

    let width = window_width.min(work_width);
    let height = window_height.min(work_height);
    let left = window
        .left
        .clamp(work_area.left, work_area.right.checked_sub(width)?);
    let top = window
        .top
        .clamp(work_area.top, work_area.bottom.checked_sub(height)?);

    Some(PixelRect {
        left,
        top,
        right: left.checked_add(width)?,
        bottom: top.checked_add(height)?,
    })
}

/// Keeps a normal restored window inside the nearest monitor's physical work
/// area. All coordinates come from the same Win32 DPI-aware coordinate space,
/// so mixed-DPI and negative-coordinate monitor arrangements stay coherent.
pub(crate) fn clamp_to_nearest_work_area<R: Runtime>(
    window: &WebviewWindow<R>,
) -> Result<(), String> {
    let native = window
        .hwnd()
        .map_err(|error| format!("get main window handle: {error}"))?;
    let hwnd = native.0 as HWND;

    // Windows already constrains maximized windows. Moving a minimized window
    // would mutate its restore placement before it has been restored.
    if unsafe { IsZoomed(hwnd) } != 0 || unsafe { IsIconic(hwnd) } != 0 {
        return Ok(());
    }

    let mut window_rect = RECT::default();
    if unsafe { GetWindowRect(hwnd, &mut window_rect) } == 0 {
        return Err(format!(
            "read main window rectangle: {}",
            std::io::Error::last_os_error()
        ));
    }

    let monitor = unsafe { MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST) };
    if monitor.is_null() {
        return Err("find nearest monitor for main window".to_owned());
    }

    let mut monitor_info = MONITORINFO {
        cbSize: size_of::<MONITORINFO>() as u32,
        ..MONITORINFO::default()
    };
    if unsafe { GetMonitorInfoW(monitor, &mut monitor_info) } == 0 {
        return Err(format!(
            "read nearest monitor work area: {}",
            std::io::Error::last_os_error()
        ));
    }

    let current = PixelRect::from(window_rect);
    let target = clamp_rect_to_work_area(current, PixelRect::from(monitor_info.rcWork))
        .ok_or_else(|| "invalid main window or monitor work-area rectangle".to_owned())?;
    if target == current {
        return Ok(());
    }

    if unsafe {
        SetWindowPos(
            hwnd,
            null_mut(),
            target.left,
            target.top,
            target.width().expect("validated target width"),
            target.height().expect("validated target height"),
            SWP_NOACTIVATE | SWP_NOOWNERZORDER | SWP_NOZORDER,
        )
    } == 0
    {
        return Err(format!(
            "clamp main window to monitor work area: {}",
            std::io::Error::last_os_error()
        ));
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{clamp_rect_to_work_area, PixelRect};

    #[test]
    fn moves_a_window_above_the_taskbar_without_resizing_it() {
        let window = PixelRect {
            left: 342,
            top: 194,
            right: 2524,
            bottom: 1600,
        };
        let work_area = PixelRect {
            left: 0,
            top: 0,
            right: 2560,
            bottom: 1528,
        };

        assert_eq!(
            clamp_rect_to_work_area(window, work_area),
            Some(PixelRect {
                left: 342,
                top: 122,
                right: 2524,
                bottom: 1528,
            })
        );
    }

    #[test]
    fn uses_negative_coordinates_for_a_left_hand_monitor() {
        let window = PixelRect {
            left: -1800,
            top: 900,
            right: -600,
            bottom: 1600,
        };
        let work_area = PixelRect {
            left: -1920,
            top: 0,
            right: 0,
            bottom: 1040,
        };

        assert_eq!(
            clamp_rect_to_work_area(window, work_area),
            Some(PixelRect {
                left: -1800,
                top: 340,
                right: -600,
                bottom: 1040,
            })
        );
    }

    #[test]
    fn shrinks_an_oversized_window_to_the_nearest_work_area() {
        let window = PixelRect {
            left: -400,
            top: -200,
            right: 2800,
            bottom: 1900,
        };
        let work_area = PixelRect {
            left: 0,
            top: 0,
            right: 2560,
            bottom: 1528,
        };

        assert_eq!(clamp_rect_to_work_area(window, work_area), Some(work_area));
    }

    #[test]
    fn preserves_a_window_that_is_already_inside_the_work_area() {
        let window = PixelRect {
            left: 120,
            top: 80,
            right: 1520,
            bottom: 980,
        };
        let work_area = PixelRect {
            left: 0,
            top: 0,
            right: 2560,
            bottom: 1528,
        };

        assert_eq!(clamp_rect_to_work_area(window, work_area), Some(window));
    }

    #[test]
    fn rejects_invalid_rectangles_instead_of_panicking() {
        let invalid_window = PixelRect {
            left: 100,
            top: 100,
            right: 100,
            bottom: 800,
        };
        let work_area = PixelRect {
            left: 0,
            top: 0,
            right: 2560,
            bottom: 1528,
        };

        assert_eq!(clamp_rect_to_work_area(invalid_window, work_area), None);
    }
}
