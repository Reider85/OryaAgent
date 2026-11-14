import { NextRequest, NextResponse } from 'next/server';

export async function GET() {
  try {
    // Fetch current permission settings from the backend
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error('Failed to fetch permissions');
    }

    const sessions = await response.json();
    const currentSession = sessions[0] || {};
    
    const permissions = {
      mode: currentSession.permission_mode || 'permissive',
      allow_list: currentSession.allow_list || [],
      deny_list: currentSession.deny_list || [],
      session_allowlist: currentSession.session_allowlist || [],
    };

    return NextResponse.json(permissions);
  } catch (error) {
    console.error('Error fetching permissions:', error);
    return NextResponse.json(
      { error: 'Failed to fetch permissions' },
      { status: 500 }
    );
  }
}

export async function PUT(request: NextRequest) {
  try {
    const permissions = await request.json();
    
    // Update permissions in the current session
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        metadata: {
          permission_mode: permissions.mode,
          allow_list: permissions.allow_list,
          deny_list: permissions.deny_list,
          session_allowlist: permissions.session_allowlist,
        },
      }),
    });

    if (!response.ok) {
      throw new Error('Failed to update permissions');
    }

    return NextResponse.json({ success: true, permissions });
  } catch (error) {
    console.error('Error updating permissions:', error);
    return NextResponse.json(
      { error: 'Failed to update permissions' },
      { status: 500 }
    );
  }
}