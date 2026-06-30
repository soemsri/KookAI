export default {
  async fetch(request, env, ctx) {
    // Add CORS headers for mobile clients
    const corsHeaders = {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, HEAD, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;
    
    // Router logic
    if (path === "/register-pin" && method === "POST") {
      try {
        const data = await request.json();
        const { pin, host_id, url: host_url, local_ip } = data;
        if (!pin || !host_id || !host_url) {
          return new Response("Missing parameters", { status: 400, headers: corsHeaders });
        }
        
        // Save pin to KV (expires in 2 minutes / 120 seconds)
        await env.REGISTRY.put(`pin:${pin}`, JSON.stringify({ host_id, url: host_url, local_ip }), { expirationTtl: 120 });
        
        // Save host_id to KV (expires in 24 hours / 86400 seconds)
        await env.REGISTRY.put(`host:${host_id}`, JSON.stringify({ url: host_url, local_ip }), { expirationTtl: 86400 });
        
        return new Response(JSON.stringify({ status: "success" }), {
          status: 200,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      } catch (err) {
        return new Response(err.message, { status: 500, headers: corsHeaders });
      }
    }
    
    if (path.startsWith("/resolve-pin/") && method === "GET") {
      const pin = path.split("/").pop();
      const val = await env.REGISTRY.get(`pin:${pin}`);
      if (!val) {
        return new Response(JSON.stringify({ error: "pin_expired_or_invalid" }), {
          status: 404,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }
      return new Response(val, {
        status: 200,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }
    
    if (path.startsWith("/resolve-host/") && method === "GET") {
      const host_id = path.split("/").pop();
      const val = await env.REGISTRY.get(`host:${host_id}`);
      if (!val) {
        return new Response(JSON.stringify({ error: "host_not_found" }), {
          status: 404,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      }
      return new Response(val, {
        status: 200,
        headers: { ...corsHeaders, "Content-Type": "application/json" }
      });
    }
    
    if (path === "/update-host" && method === "POST") {
      try {
        const data = await request.json();
        const { host_id, url: host_url, local_ip } = data;
        if (!host_id || !host_url) {
          return new Response("Missing parameters", { status: 400, headers: corsHeaders });
        }
        await env.REGISTRY.put(`host:${host_id}`, JSON.stringify({ url: host_url, local_ip }), { expirationTtl: 86400 });
        return new Response(JSON.stringify({ status: "success" }), {
          status: 200,
          headers: { ...corsHeaders, "Content-Type": "application/json" }
        });
      } catch (err) {
        return new Response(err.message, { status: 500, headers: corsHeaders });
      }
    }
    
    return new Response("Not Found", { status: 404, headers: corsHeaders });
  }
};
