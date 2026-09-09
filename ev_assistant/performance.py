"""Limit visual animation cost without changing game data or elapsed timestamps."""
async def install_frame_limit(context, fps=20, defer=False):
    if not 10 <= fps <= 60:
        raise ValueError('Frame limit must be 10–60 FPS')
    await context.add_init_script(script=r'''
    (() => {
      const nativeRequest = window.requestAnimationFrame.bind(window);
      const callbacks = new Map();
      let interval = 1000 / INITIAL_FPS;
      window.__eogEnableFrameLimit = () => { interval = 1000 / FPS_VALUE; };
      let token = 0, pending = false, lastFrame = -Infinity;
      const pump = timestamp => {
        if (timestamp - lastFrame >= interval - 1) {
          lastFrame = timestamp;
          const batch = [...callbacks.entries()];
          for (const [id, callback] of batch) {
            if (!callbacks.has(id)) continue;
            callbacks.delete(id);
            try { callback(timestamp); }
            catch (error) { setTimeout(() => { throw error; }, 0); }
          }
        }
        if (callbacks.size) nativeRequest(pump);
        else pending = false;
      };
      window.requestAnimationFrame = callback => {
        const id = ++token;
        callbacks.set(id, callback);
        if (!pending) { pending = true; nativeRequest(pump); }
        return id;
      };
      window.cancelAnimationFrame = id => callbacks.delete(id);
    })();
    '''.replace('FPS_VALUE',str(fps)).replace('INITIAL_FPS',str(60 if defer else fps)))

async def enable_frame_limit(page):
    await page.evaluate('() => window.__eogEnableFrameLimit()')
