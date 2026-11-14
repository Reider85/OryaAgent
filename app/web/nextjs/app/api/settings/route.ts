import { NextRequest, NextResponse } from 'next/server';

export async function GET() {
  try {
    // Fetch current settings from the backend
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      throw new Error('Failed to fetch settings');
    }

    const sessions = await response.json();
    
    // Get the most recent session's settings or use defaults
    const currentSession = sessions[0] || {};
    const settings = {
      model: currentSession.model || 'claude-3-sonnet-20240229',
      provider: currentSession.provider || 'anthropic',
      permission_mode: currentSession.permission_mode || 'permissive',
      allow_list: currentSession.allow_list || [],
      budget: currentSession.budget || 1000,
    };

    return NextResponse.json(settings);
  } catch (error) {
    console.error('Error fetching settings:', error);
    return NextResponse.json(
      { error: 'Failed to fetch settings' },
      { status: 500 }
    );
  }
}

export async function PUT(request: NextRequest) {
  try {
    const settings = await request.json();
    
    // Update settings in the current session
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/sessions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        metadata: {
          model: settings.model,
          provider: settings.provider,
          permission_mode: settings.permission_mode,
          allow_list: settings.allow_list,
          budget: settings.budget,
        },
      }),
    });

    if (!response.ok) {
      throw new Error('Failed to update settings');
    }

    return NextResponse.json({ success: true, settings });
  } catch (error) {
    console.error('Error updating settings:', error);
    return NextResponse.json(
      { error: 'Failed to update settings' },
      { status: 500 }
    );
  }
}