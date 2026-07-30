import scriptContent from './opencrow-cli.sh';

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const pathname = url.pathname;

    if (
      pathname === '/release/opencrow-cli.sh' ||
      pathname === '/opencrow-cli.sh' ||
      pathname === '/opencrow.sh' ||
      pathname === '/'
    ) {
      return new Response(scriptContent, {
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          'Cache-Control': 'public, max-age=300',
          'Access-Control-Allow-Origin': '*',
        },
      });
    }

    return new Response('Not Found', { status: 404 });
  },
};
