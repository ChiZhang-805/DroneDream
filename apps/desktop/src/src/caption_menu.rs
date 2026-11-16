//! A native, owned menu strip occupies the leading part of the system caption.
//! The owning window keeps its task-switcher title, DWM buttons and snap behavior.
use std::{
    cell::Cell,
    mem::size_of,
    ptr::{null, null_mut},
};
use tauri::{Emitter, WebviewWindow};
use windows_sys::Win32::{
    Graphics::Gdi::{
        CreateFontIndirectW, CreatePen, DrawTextW, GetDC, GetStockObject, GetSysColor,
        GetTextExtentPoint32W, LineTo, MoveToEx, ReleaseDC, RoundRect, SelectObject, SetBkMode,
        SetTextColor, COLOR_GRAYTEXT, COLOR_HIGHLIGHT, COLOR_HIGHLIGHTTEXT, COLOR_MENU,
        COLOR_MENUTEXT, DT_CENTER, DT_HIDEPREFIX, DT_SINGLELINE, DT_VCENTER, HDC, NULL_BRUSH,
        NULL_PEN, PS_SOLID, TRANSPARENT,
    },
    UI::{
        Accessibility::{HCF_HIGHCONTRASTON, HIGHCONTRASTW, MSAAMENUINFO, MSAA_MENU_SIG},
        Controls::{
            DRAWITEMSTRUCT, MEASUREITEMSTRUCT, ODS_DISABLED, ODS_GRAYED, ODS_HOTLIGHT, ODS_NOACCEL,
            ODS_SELECTED, ODT_MENU,
        },
    },
};
use windows_sys::{
    w,
    Win32::{
        Foundation::{HWND, LPARAM, LRESULT, POINT, RECT, SIZE, WPARAM},
        Graphics::Gdi::{
            ClientToScreen, CreateSolidBrush, DeleteObject, FillRect, InvalidateRect, HBRUSH,
        },
        UI::{
            HiDpi::{GetDpiForWindow, GetSystemMetricsForDpi, SystemParametersInfoForDpi},
            Input::KeyboardAndMouse::{
                SendInput, INPUT, INPUT_0, INPUT_KEYBOARD, KEYBDINPUT, KEYEVENTF_KEYUP, VK_CONTROL,
            },
            Shell::{DefSubclassProc, RemoveWindowSubclass, SetWindowSubclass},
            WindowsAndMessaging::*,
        },
    },
};

const BAR: windows_sys::core::PCWSTR = w!("DroneDream.CaptionMenu");
const APPLY_PENDING: u32 = WM_APP + 1;
const BACK: usize = 101;
const FORWARD: usize = 102;
const SIDEBAR: usize = 103;
const SETTINGS: usize = 104;
const CLOSE: usize = 105;
const ABOUT: usize = 106;

#[derive(Clone, Copy, Default, PartialEq, Eq, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct MenuState {
    chinese: bool,
    can_back: bool,
    can_forward: bool,
    can_sidebar: bool,
    sidebar_hidden: bool,
    can_settings: bool,
}

struct Strip {
    send_action: Box<dyn Fn(&str)>,
    names: [MSAAMENUINFO; 14],
    surface: Cell<u32>,
    brush: Cell<HBRUSH>,
    state: Cell<MenuState>,
    tracking: Cell<bool>,
    pending: Cell<Option<MenuState>>,
}

impl Strip {
    fn new(send_action: Box<dyn Fn(&str)>, brush: HBRUSH) -> Self {
        let names = [
            w!("Back"),
            w!("Forward"),
            w!("Toggle Sidebar"),
            w!("File"),
            w!("Edit"),
            w!("View"),
            w!("Help"),
            w!("后退"),
            w!("前进"),
            w!("切换侧栏"),
            w!("文件"),
            w!("编辑"),
            w!("视图"),
            w!("帮助"),
        ]
        .map(|name| MSAAMENUINFO {
            dwMSAASignature: MSAA_MENU_SIG as u32,
            cchWText: unsafe { windows_sys::Win32::Globalization::lstrlenW(name) } as u32,
            pszWText: name.cast_mut(),
        });
        Self {
            send_action,
            state: Cell::new(MenuState::default()),
            tracking: Cell::new(false),
            pending: Cell::new(None),
            brush: Cell::new(brush),
            names,
            surface: Cell::new(0xffffff),
        }
    }
}

const TITLES: [[&str; 4]; 2] = [
    ["&File", "&Edit", "&View", "&Help"],
    ["文件(&F)", "编辑(&E)", "视图(&V)", "帮助(&H)"],
];

fn blend(background: u32, foreground: u32, percent: u32) -> u32 {
    let mut result = 0;
    for shift in [0, 8, 16] {
        let base = (background >> shift) & 255;
        let ink = (foreground >> shift) & 255;
        result |= ((base * (100 - percent) + ink * percent + 50) / 100) << shift;
    }
    result
}

unsafe fn high_contrast() -> bool {
    let mut contrast = HIGHCONTRASTW {
        cbSize: size_of::<HIGHCONTRASTW>() as u32,
        ..Default::default()
    };
    SystemParametersInfoW(
        SPI_GETHIGHCONTRAST,
        contrast.cbSize,
        std::ptr::from_mut(&mut contrast).cast(),
        0,
    ) != 0
        && contrast.dwFlags & HCF_HIGHCONTRASTON != 0
}

unsafe fn with_menu_font<T>(dc: HDC, dpi: u32, draw: impl FnOnce() -> T) -> T {
    let mut metrics = NONCLIENTMETRICSW {
        cbSize: size_of::<NONCLIENTMETRICSW>() as u32,
        ..Default::default()
    };
    if SystemParametersInfoForDpi(
        SPI_GETNONCLIENTMETRICS,
        metrics.cbSize,
        std::ptr::from_mut(&mut metrics).cast(),
        0,
        dpi,
    ) == 0
    {
        return draw();
    }
    let font = CreateFontIndirectW(&metrics.lfMenuFont);
    if font.is_null() {
        return draw();
    }
    let old = SelectObject(dc, font);
    let result = draw();
    SelectObject(dc, old);
    DeleteObject(font);
    result
}

fn item_index(strip: &Strip, data: usize) -> Option<usize> {
    strip
        .names
        .iter()
        .position(|name| std::ptr::from_ref(name) as usize == data)
}

unsafe fn item_width(hwnd: HWND, dpi: u32, index: usize) -> u32 {
    let column = index % 7;
    if column < 3 {
        return 22 * dpi / 96;
    }
    let text = wide(&TITLES[index / 7][column - 3].replace('&', ""));
    let dc = GetDC(hwnd);
    let mut size = SIZE::default();
    with_menu_font(dc, dpi, || {
        GetTextExtentPoint32W(dc, text.as_ptr(), (text.len() - 1) as i32, &mut size);
    });
    ReleaseDC(hwnd, dc);
    size.cx.max(0) as u32 + 8 * dpi / 96
}

unsafe fn draw_item(hwnd: HWND, draw: &DRAWITEMSTRUCT, strip: &Strip, index: usize) {
    let column = index % 7;
    let dc = draw.hDC;
    let r = draw.rcItem;
    let selected = draw.itemState & ODS_SELECTED != 0;
    let hot = selected || draw.itemState & ODS_HOTLIGHT != 0;
    let disabled = draw.itemState & (ODS_DISABLED | ODS_GRAYED) != 0;
    let contrast = high_contrast();
    let base = if contrast {
        GetSysColor(COLOR_MENU)
    } else {
        strip.surface.get()
    };
    let foreground = GetSysColor(COLOR_MENUTEXT);
    let ink = if contrast {
        GetSysColor(if disabled {
            COLOR_GRAYTEXT
        } else if hot {
            COLOR_HIGHLIGHTTEXT
        } else {
            COLOR_MENUTEXT
        })
    } else {
        blend(
            base,
            foreground,
            if disabled {
                40
            } else if hot {
                85
            } else {
                66
            },
        )
    };
    let dpi = GetDpiForWindow(hwnd) as i32;
    let px = |n: i32| (n * dpi + 48) / 96;
    let bg = CreateSolidBrush(base);
    FillRect(dc, &r, bg);
    DeleteObject(bg);
    if hot && !disabled {
        let fill = CreateSolidBrush(if contrast {
            GetSysColor(COLOR_HIGHLIGHT)
        } else {
            blend(base, foreground, if selected { 13 } else { 7 })
        });
        let old_brush = SelectObject(dc, fill);
        let old_pen = SelectObject(dc, GetStockObject(NULL_PEN));
        RoundRect(
            dc,
            r.left + px(2),
            r.top + px(2),
            r.right - px(2),
            r.bottom - px(2),
            px(8),
            px(8),
        );
        SelectObject(dc, old_pen);
        SelectObject(dc, old_brush);
        DeleteObject(fill);
    }
    if column < 3 {
        draw_icon(dc, r, ink, dpi, column);
    } else {
        let old_mode = SetBkMode(dc, TRANSPARENT as i32);
        let old_color = SetTextColor(dc, ink);
        let title = TITLES[index / 7][column - 3];
        let hide = draw.itemState & ODS_NOACCEL != 0;
        let title = if hide {
            title.split('(').next().unwrap_or(title)
        } else {
            title
        };
        let text = wide(title);
        let mut bounds = r;
        with_menu_font(dc, dpi as u32, || {
            DrawTextW(
                dc,
                text.as_ptr(),
                -1,
                &mut bounds,
                DT_SINGLELINE | DT_CENTER | DT_VCENTER | if hide { DT_HIDEPREFIX } else { 0 },
            );
        });
        SetTextColor(dc, old_color);
        SetBkMode(dc, old_mode);
    }
}

unsafe fn draw_icon(dc: HDC, r: RECT, ink: u32, dpi: i32, index: usize) {
    let px = |n: i32| (n * dpi + 48) / 96;
    let cx = (r.left + r.right) / 2;
    let cy = (r.top + r.bottom) / 2;
    let pen = CreatePen(PS_SOLID, px(1).max(1), ink);
    let old_pen = SelectObject(dc, pen);
    let old_brush = SelectObject(dc, GetStockObject(NULL_BRUSH));
    let line = |x, y, x2, y2| {
        MoveToEx(dc, x, y, null_mut());
        LineTo(dc, x2, y2);
    };
    match index {
        2 => {
            RoundRect(
                dc,
                cx - px(7),
                cy - px(6),
                cx + px(7) + 1,
                cy + px(6) + 1,
                px(4),
                px(4),
            );
            line(cx - px(2), cy - px(6), cx - px(2), cy + px(6));
        }
        id => {
            let dir = if id == 0 { -1 } else { 1 };
            let tip = cx + dir * px(6);
            line(cx - dir * px(6), cy, tip, cy);
            line(tip - dir * px(5), cy - px(5), tip, cy);
            line(tip, cy, tip - dir * px(5), cy + px(5));
        }
    }
    SelectObject(dc, old_brush);
    SelectObject(dc, old_pen);
    DeleteObject(pen);
}

fn wide(label: &str) -> Vec<u16> {
    label.encode_utf16().chain(Some(0)).collect()
}

unsafe fn item(menu: HMENU, flags: u32, id: usize, label: &str) {
    AppendMenuW(menu, flags, id, wide(label).as_ptr());
}

unsafe fn make_menu(s: MenuState, strip: &Strip) -> HMENU {
    let label = |en, zh| if s.chinese { zh } else { en };
    let root = CreateMenu();
    for (index, id) in [BACK, FORWARD, SIDEBAR].into_iter().enumerate() {
        let info = &strip.names[index + if s.chinese { 7 } else { 0 }];
        AppendMenuW(root, MF_OWNERDRAW, id, std::ptr::from_ref(info).cast());
    }
    let file = CreatePopupMenu();
    item(file, MF_STRING, SETTINGS, label("&Settings…", "设置(&S)…"));
    item(
        file,
        MF_STRING,
        CLOSE,
        label("&Close Window\tAlt+F4", "关闭窗口(&C)\tAlt+F4"),
    );
    let edit = CreatePopupMenu();
    for (key, en, zh) in [
        (b'Z', "&Undo\tCtrl+Z", "撤销(&U)\tCtrl+Z"),
        (b'Y', "&Redo\tCtrl+Y", "重做(&R)\tCtrl+Y"),
        (b'X', "Cu&t\tCtrl+X", "剪切(&T)\tCtrl+X"),
        (b'C', "&Copy\tCtrl+C", "复制(&C)\tCtrl+C"),
        (b'V', "&Paste\tCtrl+V", "粘贴(&P)\tCtrl+V"),
        (b'A', "Select &All\tCtrl+A", "全选(&A)\tCtrl+A"),
    ] {
        if key == b'X' {
            AppendMenuW(edit, MF_SEPARATOR, 0, null());
        }
        item(edit, MF_STRING, key as usize, label(en, zh));
    }
    let view = CreatePopupMenu();
    item(view, MF_STRING, BACK, label("&Back", "后退(&B)"));
    item(view, MF_STRING, FORWARD, label("&Forward", "前进(&F)"));
    item(
        view,
        MF_STRING,
        SIDEBAR,
        if s.sidebar_hidden {
            label("&Show Sidebar", "显示侧栏(&S)")
        } else {
            label("&Hide Sidebar", "收起侧栏(&S)")
        },
    );
    let help = CreatePopupMenu();
    item(
        help,
        MF_STRING,
        ABOUT,
        label("&About DroneDream", "关于 DroneDream(&A)"),
    );
    for (i, menu) in [file, edit, view, help].into_iter().enumerate() {
        let title = TITLES[s.chinese as usize][i];
        item(root, MF_POPUP, menu as usize, title);
        let name = &strip.names[if s.chinese { 7 } else { 0 } + i + 3];
        let info = MENUITEMINFOW {
            cbSize: size_of::<MENUITEMINFOW>() as u32,
            fMask: MIIM_FTYPE | MIIM_DATA,
            fType: MFT_OWNERDRAW,
            dwItemData: std::ptr::from_ref(name) as usize,
            ..Default::default()
        };
        SetMenuItemInfoW(root, (i + 3) as u32, 1, &info);
    }
    for (menu, id, enabled) in [
        (file, SETTINGS, s.can_settings),
        (view, BACK, s.can_back),
        (view, FORWARD, s.can_forward),
        (view, SIDEBAR, s.can_sidebar),
    ] {
        EnableMenuItem(
            menu,
            id as u32,
            if enabled { MF_ENABLED } else { MF_GRAYED },
        );
    }
    for (pos, enabled) in [s.can_back, s.can_forward, s.can_sidebar]
        .into_iter()
        .enumerate()
    {
        EnableMenuItem(
            root,
            pos as u32,
            MF_BYPOSITION | if enabled { MF_ENABLED } else { MF_GRAYED },
        );
    }
    root
}

unsafe fn paint_menu(bar: HWND, brush: HBRUSH) {
    let info = MENUINFO {
        cbSize: size_of::<MENUINFO>() as u32,
        fMask: MIM_BACKGROUND,
        hbrBack: brush,
        ..Default::default()
    };
    SetMenuInfo(GetMenu(bar), &info);
    DrawMenuBar(bar);
    InvalidateRect(bar, null(), 1);
}

unsafe fn place(owner: HWND, bar: HWND) {
    if IsWindowVisible(owner) == 0
        || IsIconic(owner) != 0
        || GetWindowLongW(owner, GWL_STYLE) as u32 & WS_CAPTION != WS_CAPTION
    {
        ShowWindow(bar, SW_HIDE);
        return;
    }
    let dpi = GetDpiForWindow(owner);
    let height = GetSystemMetricsForDpi(SM_CYCAPTION, dpi);
    let mut origin = POINT::default();
    ClientToScreen(owner, &mut origin);
    let mut last = RECT::default();
    let mut first = RECT::default();
    let menu = GetMenu(bar);
    // The host starts wide so Windows lays out all seven items on one line.
    if GetMenuItemRect(bar, menu, 0, &mut first) == 0
        || GetMenuItemRect(bar, menu, 6, &mut last) == 0
    {
        return;
    }
    let width = last.right - first.left + 8 * (dpi as i32) / 96;
    // USER32 paints a separator immediately below the menu items. End the host
    // at the row's last visible pixel and let the original caption fill the rest.
    let row_height = (last.bottom - first.top).clamp(1, height);
    SetWindowPos(
        bar,
        null_mut(),
        origin.x,
        origin.y - (height + row_height) / 2,
        width,
        row_height,
        SWP_NOACTIVATE | SWP_NOZORDER | SWP_SHOWWINDOW,
    );
}

unsafe extern "system" fn owner_proc(
    hwnd: HWND,
    msg: u32,
    w: WPARAM,
    l: LPARAM,
    id: usize,
    bar: usize,
) -> LRESULT {
    let bar = bar as HWND;
    if msg == WM_NCDESTROY {
        RemovePropW(hwnd, BAR);
        RemoveWindowSubclass(hwnd, Some(owner_proc), id);
        return DefSubclassProc(hwnd, msg, w, l);
    }
    let result = DefSubclassProc(hwnd, msg, w, l);
    if msg == WM_ENABLE && IsWindow(bar) != 0 {
        windows_sys::Win32::UI::Input::KeyboardAndMouse::EnableWindow(bar, (w != 0) as i32);
    }
    if matches!(
        msg,
        WM_WINDOWPOSCHANGED | WM_DPICHANGED | WM_SHOWWINDOW | WM_STYLECHANGED
    ) && IsWindow(bar) != 0
    {
        place(hwnd, bar);
    }
    result
}

// Use the same editing shortcuts as the native Windows Edit menu. Give focus
// back to our owner before issuing a shortcut, including when its menu had focus.
unsafe fn edit_shortcut(owner: HWND, key: u16) {
    if GetForegroundWindow() != owner {
        SetForegroundWindow(owner);
        if GetForegroundWindow() != owner {
            return;
        }
    }
    let input = |vk, flags| INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: vk,
                dwFlags: flags,
                ..Default::default()
            },
        },
    };
    let keys = [
        input(VK_CONTROL, 0),
        input(key, 0),
        input(key, KEYEVENTF_KEYUP),
        input(VK_CONTROL, KEYEVENTF_KEYUP),
    ];
    SendInput(keys.len() as u32, keys.as_ptr(), size_of::<INPUT>() as i32);
}

unsafe extern "system" fn bar_proc(
    hwnd: HWND,
    msg: u32,
    w: WPARAM,
    l: LPARAM,
    id: usize,
    data: usize,
) -> LRESULT {
    let strip = &*(data as *const Strip);
    let owner = GetWindow(hwnd, GW_OWNER);
    match msg {
        WM_MEASUREITEM => {
            let m = &mut *(l as *mut MEASUREITEMSTRUCT);
            if m.CtlType == ODT_MENU {
                if let Some(index) = item_index(strip, m.itemData) {
                    let dpi = GetDpiForWindow(hwnd);
                    m.itemHeight = GetSystemMetricsForDpi(SM_CYMENU, dpi) as u32;
                    m.itemWidth = item_width(hwnd, dpi, index);
                    return 1;
                }
            }
        }
        WM_DRAWITEM => {
            let d = &*(l as *const DRAWITEMSTRUCT);
            if d.CtlType == ODT_MENU {
                if let Some(index) = item_index(strip, d.itemData) {
                    draw_item(hwnd, d, strip, index);
                    return 1;
                }
            }
        }
        WM_MENUCHAR if l as HMENU == GetMenu(hwnd) => {
            if let Some(index) = "fevh"
                .bytes()
                .position(|ch| u32::from(ch) == ((w as u32 & 0xffff) | 0x20))
            {
                return ((MNC_EXECUTE << 16) | (index as u32 + 3)) as LRESULT;
            }
        }
        WM_ENTERMENULOOP => strip.tracking.set(true),
        WM_EXITMENULOOP => {
            strip.tracking.set(false);
            if strip.pending.get().is_some() {
                PostMessageW(hwnd, APPLY_PENDING, 0, 0);
            }
        }
        APPLY_PENDING => {
            if let Some(state) = strip.pending.take() {
                update_menu(owner, state);
            }
            return 0;
        }
        WM_MOUSEACTIVATE => return MA_NOACTIVATE as isize,
        WM_ERASEBKGND => {
            let mut r = RECT::default();
            GetClientRect(hwnd, &mut r);
            FillRect(w as _, &r, strip.brush.get());
            return 1;
        }
        WM_COMMAND => {
            let command = w & 0xffff;
            match command {
                BACK | FORWARD | SIDEBAR | SETTINGS => {
                    let name = match command {
                        BACK => "back",
                        FORWARD => "forward",
                        SIDEBAR => "sidebar",
                        _ => "settings",
                    };
                    (strip.send_action)(name);
                }
                CLOSE => {
                    PostMessageW(owner, WM_CLOSE, 0, 0);
                }
                ABOUT => {
                    let title = if strip.state.get().chinese {
                        "关于 DroneDream"
                    } else {
                        "About DroneDream"
                    };
                    let mut name = [0u16; 128];
                    let count = GetWindowTextW(owner, name.as_mut_ptr(), name.len() as i32);
                    let edition = String::from_utf16_lossy(&name[..count as usize]);
                    let details = format!(
                        "{}\n{} · Build {}",
                        edition,
                        env!("CARGO_PKG_VERSION"),
                        env!("DRONEDREAM_BUILD_NUMBER")
                    );
                    MessageBoxW(
                        owner,
                        wide(&details).as_ptr(),
                        wide(title).as_ptr(),
                        MB_OK | MB_ICONINFORMATION,
                    );
                }
                65 | 67 | 86 | 88 | 89 | 90 => edit_shortcut(owner, command as u16),
                _ => {}
            }
            return 0;
        }
        WM_NCDESTROY => {
            RemoveWindowSubclass(hwnd, Some(bar_proc), id);
            if GetPropW(owner, BAR) == hwnd {
                RemovePropW(owner, BAR);
            }
            let brush = strip.brush.get();
            let result = DefSubclassProc(hwnd, msg, w, l);
            DeleteObject(brush);
            drop(Box::from_raw(data as *mut Strip));
            return result;
        }
        _ => {}
    }
    DefSubclassProc(hwnd, msg, w, l)
}

pub(crate) fn attach(window: &WebviewWindow) -> Result<(), String> {
    let owner = window.hwnd().map_err(|e| e.to_string())?.0.cast();
    let sender = window.clone();
    unsafe {
        attach_to(
            owner,
            Box::new(move |action| {
                let _ = sender.emit("caption-action", action);
            }),
        )
    }
}

unsafe fn attach_to(owner: HWND, send_action: Box<dyn Fn(&str)>) -> Result<(), String> {
    {
        let state = MenuState::default();
        // An owned tool window groups with the workspace in the z-order and is
        // automatically destroyed with it. Its menu remains a real Win32 HMENU.
        let class = w!("DroneDreamCaptionMenu");
        let instance = windows_sys::Win32::System::LibraryLoader::GetModuleHandleW(null());
        let wc = WNDCLASSW {
            hInstance: instance,
            lpfnWndProc: Some(DefWindowProcW),
            lpszClassName: class,
            ..Default::default()
        };
        RegisterClassW(&wc);
        let bar = CreateWindowExW(
            WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
            class,
            w!("DroneDream menu"),
            WS_POPUP,
            0,
            0,
            640,
            32,
            owner,
            null_mut(),
            instance,
            null(),
        );
        if bar.is_null() {
            return Err(std::io::Error::last_os_error().to_string());
        }
        let brush = CreateSolidBrush(0xffffff);
        let data = Box::into_raw(Box::new(Strip::new(send_action, brush)));
        if SetWindowSubclass(bar, Some(bar_proc), 1, data as usize) == 0 {
            drop(Box::from_raw(data));
            DeleteObject(brush);
            DestroyWindow(bar);
            return Err("Could not attach caption menu".into());
        }
        SetWindowLongPtrW(bar, GWLP_USERDATA, data as isize);
        if SetPropW(owner, BAR, bar) == 0
            || SetWindowSubclass(owner, Some(owner_proc), 1, bar as usize) == 0
        {
            RemovePropW(owner, BAR);
            DestroyWindow(bar);
            return Err("Could not track caption menu".into());
        }
        let menu = make_menu(state, &*data);
        if SetMenu(bar, menu) == 0 {
            DestroyMenu(menu);
            DestroyWindow(bar);
            return Err("Could not initialize caption commands".into());
        }
        paint_menu(bar, brush);
        place(owner, bar);
    }
    Ok(())
}

unsafe fn strip_for(owner: HWND) -> Option<(HWND, *const Strip)> {
    let bar = GetPropW(owner, BAR) as HWND;
    if bar.is_null() {
        return None;
    }
    let data = GetWindowLongPtrW(bar, GWLP_USERDATA);
    if data == 0 {
        return None;
    }
    Some((bar, data as *const Strip))
}

pub(crate) unsafe fn color(owner: HWND, value: u32) {
    if let Some((bar, data)) = strip_for(owner) {
        let strip = &*data;
        let next = CreateSolidBrush(value);
        if !next.is_null() {
            strip.surface.set(value);
            let old = strip.brush.replace(next);
            paint_menu(bar, next);
            DeleteObject(old);
        }
    }
}

unsafe fn update_menu(owner: HWND, state: MenuState) {
    if let Some((bar, strip)) = strip_for(owner) {
        let strip = &*strip;
        if strip.tracking.get() {
            strip.pending.set(Some(state));
            return;
        }
        if strip.state.get() == state {
            return;
        }
        let old = GetMenu(bar);
        let next = make_menu(state, strip);
        if SetMenu(bar, next) != 0 {
            strip.state.set(state);
            DestroyMenu(old);
            // Allow a longer translation to lay out before measuring it.
            SetWindowPos(
                bar,
                null_mut(),
                0,
                0,
                640 * GetDpiForWindow(bar) as i32 / 96,
                32,
                SWP_NOMOVE | SWP_NOACTIVATE | SWP_NOZORDER,
            );
            paint_menu(bar, strip.brush.get());
            place(owner, bar);
        } else {
            DestroyMenu(next);
        }
    }
}

#[tauri::command]
pub(crate) fn configure_caption_menu(
    window: WebviewWindow,
    state: MenuState,
) -> Result<(), String> {
    let own = window.clone();
    window
        .run_on_main_thread(move || unsafe {
            let Ok(hwnd) = own.hwnd() else { return };
            update_menu(hwnd.0.cast(), state);
        })
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub(crate) fn focus_caption_menu(window: WebviewWindow, mnemonic: String) -> Result<(), String> {
    let key = match mnemonic.as_str() {
        "file" => b'f',
        "edit" => b'e',
        "view" => b'v',
        "help" => b'h',
        _ => return Ok(()),
    };
    let own = window.clone();
    window
        .run_on_main_thread(move || unsafe {
            if let Ok(hwnd) = own.hwnd() {
                let bar = GetPropW(hwnd.0.cast(), BAR) as HWND;
                if !bar.is_null() {
                    PostMessageW(bar, WM_SYSCOMMAND, SC_KEYMENU as usize, key as isize);
                }
            }
        })
        .map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::rc::Rc;

    // Capture a genuine menu row, then ask the same owner-draw callback to paint
    // the Help item in the two states Windows sends during mouse/menu tracking.
    unsafe fn verify_caption_pixels(bar: HWND, owner: HWND) {
        use windows_sys::Win32::{
            Graphics::Gdi::{CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, GetPixel},
            Storage::Xps::PrintWindow,
        };
        if high_contrast() {
            return;
        }
        let base = 0xfff5f8;
        color(owner, base);
        let mut row = RECT::default();
        GetWindowRect(bar, &mut row);
        let width = row.right - row.left;
        let height = row.bottom - row.top;
        let screen = GetDC(bar);
        let dc = CreateCompatibleDC(screen);
        let bitmap = CreateCompatibleBitmap(screen, width, height);
        let old = SelectObject(dc, bitmap);
        assert_ne!(PrintWindow(bar, dc, 2), 0);
        for x in 0..width {
            assert_eq!(GetPixel(dc, x, height - 1), base, "divider at x={x}");
        }
        let mut help = RECT::default();
        GetMenuItemRect(bar, GetMenu(bar), 6, &mut help);
        help.left -= row.left;
        help.right -= row.left;
        help.top -= row.top;
        help.bottom -= row.top;
        let (_, strip) = strip_for(owner).unwrap();
        let name = &(*strip).names[13];
        let scaled = |n| (n * GetDpiForWindow(bar) as i32 + 48) / 96;
        for (state, pct) in [(ODS_HOTLIGHT, 7), (ODS_SELECTED, 13)] {
            let d = DRAWITEMSTRUCT {
                CtlType: ODT_MENU,
                itemState: state,
                rcItem: help,
                hDC: dc,
                itemData: std::ptr::from_ref(name) as usize,
                ..Default::default()
            };
            assert_eq!(
                SendMessageW(bar, WM_DRAWITEM, 0, std::ptr::from_ref(&d) as LPARAM),
                1
            );
            let mid = (help.left + help.right) / 2;
            assert_eq!(GetPixel(dc, mid, help.top), base);
            assert_eq!(
                GetPixel(dc, help.left + scaled(2), help.top + scaled(2)),
                base
            );
            assert_eq!(
                GetPixel(dc, mid, help.top + scaled(3)),
                blend(base, GetSysColor(COLOR_MENUTEXT), pct)
            );
        }
        SelectObject(dc, old);
        DeleteObject(bitmap);
        DeleteDC(dc);
        ReleaseDC(bar, screen);
    }

    #[test]
    fn caption_tracks_the_decorated_owner_and_dispatches_localized_commands() {
        unsafe {
            let owner = CreateWindowExW(
                WS_EX_TOOLWINDOW,
                w!("STATIC"),
                w!("Window test"),
                WS_OVERLAPPEDWINDOW,
                -4000,
                -3000,
                980,
                700,
                null_mut(),
                null_mut(),
                null_mut(),
                null(),
            );
            assert!(!owner.is_null());
            let received = Rc::new(std::cell::RefCell::new(Vec::new()));
            let out = received.clone();
            attach_to(
                owner,
                Box::new(move |item| out.borrow_mut().push(item.to_owned())),
            )
            .unwrap();
            ShowWindow(owner, SW_SHOWNOACTIVATE);
            let bar = GetPropW(owner, BAR) as HWND;
            assert_eq!(GetWindow(bar, GW_OWNER), owner);
            assert_eq!(
                GetWindowLongW(owner, GWL_STYLE) as u32 & WS_OVERLAPPEDWINDOW,
                WS_OVERLAPPEDWINDOW
            );
            let menu = GetMenu(bar);
            assert_eq!(GetMenuItemCount(menu), 7);
            assert!(GetMenuState(menu, 0, MF_BYPOSITION) & MF_GRAYED != 0);
            let mut title = [0u16; 32];
            let len = GetMenuStringW(menu, 3, title.as_mut_ptr(), 32, MF_BYPOSITION);
            assert_eq!(String::from_utf16_lossy(&title[..len as usize]), "&File");
            update_menu(
                owner,
                MenuState {
                    chinese: true,
                    can_settings: true,
                    can_back: true,
                    can_sidebar: true,
                    ..Default::default()
                },
            );
            let menu = GetMenu(bar);
            let len = GetMenuStringW(menu, 3, title.as_mut_ptr(), 32, MF_BYPOSITION);
            assert_eq!(String::from_utf16_lossy(&title[..len as usize]), "文件(&F)");
            SetWindowPos(
                owner,
                null_mut(),
                -3800,
                -2700,
                1000,
                720,
                SWP_NOACTIVATE | SWP_NOZORDER,
            );
            let mut br = RECT::default();
            GetWindowRect(bar, &mut br);
            let mut origin = POINT::default();
            ClientToScreen(owner, &mut origin);
            assert_eq!(br.left, origin.x);
            let caption_height = GetSystemMetricsForDpi(SM_CYCAPTION, GetDpiForWindow(owner));
            assert!(br.top >= origin.y - caption_height && br.bottom <= origin.y);
            assert_ne!(IsWindowVisible(bar), 0);
            let mut last = RECT::default();
            assert_ne!(GetMenuItemRect(bar, menu, 6, &mut last), 0);
            assert!(last.right <= br.right && last.top >= br.top);
            assert_eq!(
                last.bottom, br.bottom,
                "the native separator must be outside the strip"
            );
            assert_eq!(
                SendMessageW(bar, WM_MENUCHAR, b'h' as usize, menu as LPARAM),
                ((MNC_EXECUTE << 16) | 6) as LRESULT
            );
            let x = (last.right + last.left) / 2;
            let y = (last.bottom + last.top) / 2;
            let lp = (((y as u32 & 0xffff) << 16) | (x as u32 & 0xffff)) as LPARAM;
            assert_eq!(SendMessageW(bar, WM_NCHITTEST, 0, lp), HTMENU as LRESULT);
            verify_caption_pixels(bar, owner);
            SendMessageW(bar, WM_COMMAND, SETTINGS, 0);
            assert_eq!(*received.borrow(), ["settings"]);
            ShowWindow(owner, SW_MINIMIZE);
            assert_eq!(IsWindowVisible(bar), 0);
            DestroyWindow(owner);
            assert_eq!(IsWindow(bar), 0);
        }
    }
}
